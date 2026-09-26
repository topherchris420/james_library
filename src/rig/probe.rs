//! Safe, bounded HTTP probes for local services.
//!
//! Probes never contact remote endpoints: hosts are classified with
//! [`crate::providers::locality`] first and anything not loopback or
//! private-network is reported as [`ProbeOutcome::NotProbed`]. Hostnames are
//! resolved once, every address must be local, and the request is pinned to
//! the verified address so a second lookup cannot redirect it (DNS
//! rebinding). The client bypasses proxies (local traffic must not be
//! forwarded off-box), follows no redirects, uses short timeouts, and caps
//! response size.

use crate::providers::locality::{
    EndpointLocality, classify_addresses, classify_host, is_literal_host,
};
use std::net::SocketAddr;
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

fn client_builder() -> reqwest::ClientBuilder {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(REQUEST_TIMEOUT)
}

/// Result of verifying a host before contacting it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedHost {
    pub locality: EndpointLocality,
    /// Verified address to pin for hostnames (`None` for literals).
    pub pinned: Option<SocketAddr>,
}

/// Resolve and classify `host:port` asynchronously; every address must be
/// local. Literal hosts are classified without a lookup.
pub async fn verify_host(host: &str, port: u16) -> VerifiedHost {
    let bare = host.trim_start_matches('[').trim_end_matches(']');
    if is_literal_host(bare) {
        return VerifiedHost {
            locality: classify_host(bare),
            pinned: None,
        };
    }
    let lookup = tokio::time::timeout(CONNECT_TIMEOUT, tokio::net::lookup_host((bare, port))).await;
    let addresses: Vec<SocketAddr> = match lookup {
        Ok(Ok(addresses)) => addresses.collect(),
        _ => Vec::new(),
    };
    let ips: Vec<_> = addresses.iter().map(SocketAddr::ip).collect();
    let locality = classify_addresses(&ips);
    VerifiedHost {
        pinned: locality
            .is_local()
            .then(|| addresses.first().copied())
            .flatten(),
        locality,
    }
}

/// Resolved locality of a URL (remote when unparsable or unresolvable).
pub async fn endpoint_locality(url: &str) -> EndpointLocality {
    let Ok(parsed) = reqwest::Url::parse(url.trim()) else {
        return EndpointLocality::Remote;
    };
    let (Some(host), Some(port)) = (parsed.host_str(), parsed.port_or_known_default()) else {
        return EndpointLocality::Remote;
    };
    verify_host(host, port).await.locality
}

impl ProbeClient {
    pub fn new() -> Self {
        Self {
            http: client_builder().build().ok(),
        }
    }

    /// GET `url` if it is a local endpoint. `bearer` is sent only when set.
    pub async fn get(&self, url: &str, bearer: Option<&str>) -> ProbeOutcome {
        let Ok(parsed) = reqwest::Url::parse(url.trim()) else {
            return ProbeOutcome::NotProbed;
        };
        let (Some(host), Some(port)) = (parsed.host_str(), parsed.port_or_known_default()) else {
            return ProbeOutcome::NotProbed;
        };
        let verified = verify_host(host, port).await;
        if !verified.locality.is_local() {
            return ProbeOutcome::NotProbed;
        }
        let pinned_client;
        let http = match verified.pinned {
            // Pin the verified address so the request cannot be re-resolved.
            Some(address) => {
                pinned_client = client_builder().resolve(host, address).build().ok();
                pinned_client.as_ref()
            }
            None => self.http.as_ref(),
        };
        let Some(http) = http else {
            return ProbeOutcome::Unreachable {
                reason: "HTTP client unavailable".into(),
            };
        };
        let mut request = http.get(parsed);
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
        let verified = verify_host(host, port).await;
        if !verified.locality.is_local() {
            return false;
        }
        let address = match verified.pinned {
            Some(address) => address.to_string(),
            None if host.contains(':') => format!("[{host}]:{port}"),
            None => format!("{host}:{port}"),
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
    async fn localhost_names_resolve_and_unresolvable_names_are_not_probed() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/ok"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"a": 1})))
            .mount(&server)
            .await;
        let port = server.address().port();
        let client = ProbeClient::new();
        let ok = client
            .get(&format!("http://localhost:{port}/ok"), None)
            .await;
        assert!(ok.ok_json().is_some(), "{ok:?}");
        let unresolvable = client
            .get("http://rig-no-such-host.invalid:8080/v1/models", None)
            .await;
        assert_eq!(unresolvable, ProbeOutcome::NotProbed);
        assert_eq!(
            endpoint_locality("http://rig-no-such-host.invalid/").await,
            EndpointLocality::Remote
        );
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
