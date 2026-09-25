//! Safe, bounded HTTP probes for local services.
//!
//! Probes never contact remote endpoints: URLs are classified with
//! [`crate::providers::locality`] first and anything not loopback or
//! private-network is reported as [`ProbeOutcome::NotProbed`]. The client
//! bypasses proxies (local traffic must not be forwarded off-box), follows
//! no redirects, uses short timeouts, and caps response size.

use crate::providers::locality::classify_endpoint;
use std::time::Duration;

const CONNECT_TIMEOUT: Duration = Duration::from_millis(800);
const REQUEST_TIMEOUT: Duration = Duration::from_millis(2500);
const MAX_BODY_BYTES: usize = 1024 * 1024;

/// Result of one probe request.
#[derive(Debug, Clone, PartialEq)]
pub enum ProbeOutcome {
    /// HTTP response with a JSON body.
    Json {
        status: u16,
        body: serde_json::Value,
    },
    /// HTTP response whose body was not JSON (or was too large).
    Http { status: u16 },
    /// Connection failed or timed out.
    Unreachable { reason: String },
    /// The endpoint is not local; no request was made.
    NotProbed,
}

impl ProbeOutcome {
    pub fn status(&self) -> Option<u16> {
        match self {
            Self::Json { status, .. } | Self::Http { status } => Some(*status),
            Self::Unreachable { .. } | Self::NotProbed => None,
        }
    }

    pub fn is_reachable(&self) -> bool {
        self.status().is_some()
    }

    /// JSON body of a 2xx response.
    pub fn ok_json(&self) -> Option<&serde_json::Value> {
        match self {
            Self::Json { status, body } if (200..300).contains(status) => Some(body),
            _ => None,
        }
    }
}

/// HTTP client restricted to local-service probing.
#[derive(Debug, Clone)]
pub struct ProbeClient {
    http: Option<reqwest::Client>,
}

impl Default for ProbeClient {
    fn default() -> Self {
        Self::new()
    }
}

impl ProbeClient {
    pub fn new() -> Self {
        let http = reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .build()
            .ok();
        Self { http }
    }

    /// GET `url` if it is a local endpoint. `bearer` is sent only when set.
    pub async fn get(&self, url: &str, bearer: Option<&str>) -> ProbeOutcome {
        if !classify_endpoint(url).is_local() {
            return ProbeOutcome::NotProbed;
        }
        let Some(http) = self.http.as_ref() else {
            return ProbeOutcome::Unreachable {
                reason: "HTTP client unavailable".into(),
            };
        };
        let mut request = http.get(url);
        if let Some(token) = bearer.map(str::trim).filter(|token| !token.is_empty()) {
            request = request.bearer_auth(token);
        }
        let mut response = match request.send().await {
            Ok(response) => response,
            Err(error) => {
                let reason = if error.is_timeout() {
                    "timed out"
                } else if error.is_connect() {
                    "connection refused"
                } else {
                    "request failed"
                };
                return ProbeOutcome::Unreachable {
                    reason: reason.into(),
                };
            }
        };
        let status = response.status().as_u16();
        let mut body = Vec::new();
        loop {
            match response.chunk().await {
                Ok(Some(chunk)) => {
                    if body.len() + chunk.len() > MAX_BODY_BYTES {
                        return ProbeOutcome::Http { status };
                    }
                    body.extend_from_slice(&chunk);
                }
                Ok(None) => break,
                Err(_) => return ProbeOutcome::Http { status },
            }
        }
        match serde_json::from_slice(&body) {
            Ok(body) => ProbeOutcome::Json { status, body },
            Err(_) => ProbeOutcome::Http { status },
        }
    }

    /// Whether a TCP connection to a local `host:port` succeeds.
    pub async fn tcp_open(&self, host: &str, port: u16) -> bool {
        let host = host.trim_start_matches('[').trim_end_matches(']');
        if !crate::providers::locality::classify_host(host).is_local() {
            return false;
        }
        let address = if host.contains(':') {
            format!("[{host}]:{port}")
        } else {
            format!("{host}:{port}")
        };
        matches!(
            tokio::time::timeout(CONNECT_TIMEOUT, tokio::net::TcpStream::connect(address)).await,
            Ok(Ok(_))
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn remote_endpoints_are_never_contacted() {
        let client = ProbeClient::new();
        assert_eq!(
            client.get("https://api.openai.com/v1/models", None).await,
            ProbeOutcome::NotProbed
        );
        assert_eq!(client.get("not a url", None).await, ProbeOutcome::NotProbed);
        assert!(!client.tcp_open("example.com", 443).await);
    }

    #[tokio::test]
    async fn local_json_and_status_codes_are_reported() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/ok"))
            .and(header("authorization", "Bearer probe-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"a": 1})))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/text"))
            .respond_with(ResponseTemplate::new(503).set_body_string("loading"))
            .mount(&server)
            .await;
        let client = ProbeClient::new();
        let ok = client
            .get(&format!("{}/ok", server.uri()), Some("probe-token"))
            .await;
        assert_eq!(ok.ok_json().unwrap()["a"], 1);
        let text = client.get(&format!("{}/text", server.uri()), None).await;
        assert_eq!(text, ProbeOutcome::Http { status: 503 });
        assert!(text.ok_json().is_none());
    }

    #[tokio::test]
    async fn redirects_are_not_followed() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/redirect"))
            .respond_with(
                ResponseTemplate::new(302).insert_header("location", "https://example.com/"),
            )
            .mount(&server)
            .await;
        let outcome = ProbeClient::new()
            .get(&format!("{}/redirect", server.uri()), None)
            .await;
        assert_eq!(outcome.status(), Some(302));
    }

    #[tokio::test]
    async fn closed_local_port_is_unreachable() {
        let port = crate::rig::test_support::unused_local_port();
        let outcome = ProbeClient::new()
            .get(&format!("http://127.0.0.1:{port}/v1/models"), None)
            .await;
        assert!(
            matches!(outcome, ProbeOutcome::Unreachable { .. }),
            "{outcome:?}"
        );
        assert!(!ProbeClient::new().tcp_open("127.0.0.1", port).await);
    }
}
