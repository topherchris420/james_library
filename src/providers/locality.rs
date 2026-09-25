//! Inference endpoint locality: where a provider actually sends prompts.
//!
//! `ProviderInfo::local` means "needs no API key"; it is not a privacy
//! statement (CLI wrappers such as `claude-code` call hosted services). This
//! module answers the privacy question instead: given a provider id and the
//! base URL the factory would use, is inference performed on this machine, on
//! the local network, or by a remote/hosted service?
//!
//! Used by the provider factory to enforce `[rig] privacy = "local"` and by
//! `rain rig` status/doctor reporting. Classification is purely syntactic (no
//! DNS lookups); hostnames that are not provably local are treated as remote
//! so enforcement fails closed.

use serde::Serialize;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

/// Default llama.cpp `llama-server` OpenAI-compatible base URL.
pub const LLAMACPP_DEFAULT_BASE_URL: &str = "http://localhost:8080/v1";
/// Default LM Studio OpenAI-compatible base URL.
pub const LMSTUDIO_DEFAULT_BASE_URL: &str = "http://localhost:1234/v1";
/// Default Ollama native API base URL.
pub const OLLAMA_DEFAULT_BASE_URL: &str = "http://localhost:11434";
/// Default SGLang OpenAI-compatible base URL.
pub const SGLANG_DEFAULT_BASE_URL: &str = "http://localhost:30000/v1";
/// Default vLLM OpenAI-compatible base URL.
pub const VLLM_DEFAULT_BASE_URL: &str = "http://localhost:8000/v1";
/// Default Osaurus OpenAI-compatible base URL.
pub const OSAURUS_DEFAULT_BASE_URL: &str = "http://localhost:1337/v1";
/// Default LiteLLM proxy base URL.
pub const LITELLM_DEFAULT_BASE_URL: &str = "http://localhost:4000/v1";

/// Where an inference endpoint lives, from a privacy perspective.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EndpointLocality {
    /// This machine (127.0.0.0/8, ::1, `localhost`).
    Loopback,
    /// Non-globally-routable network (RFC 1918, link-local, ULA, `.local`).
    PrivateNetwork,
    /// Anything else, including unparsable URLs and public hostnames.
    Remote,
}

impl EndpointLocality {
    /// Whether `privacy = "local"` accepts this endpoint.
    pub fn is_local(self) -> bool {
        !matches!(self, Self::Remote)
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Loopback => "local",
            Self::PrivateNetwork => "lan",
            Self::Remote => "remote",
        }
    }
}

/// Classify a host string (IP literal, bracketed IPv6, or hostname).
pub fn classify_host(host: &str) -> EndpointLocality {
    let bare = host
        .trim()
        .trim_start_matches('[')
        .trim_end_matches(']')
        .trim_end_matches('.')
        .to_ascii_lowercase();
    if bare == "localhost" || bare.ends_with(".localhost") {
        return EndpointLocality::Loopback;
    }
    if let Ok(ip) = bare.parse::<IpAddr>() {
        return classify_ip(ip);
    }
    // RFC 6762 (mDNS) and RFC 8375 names are local-network by definition.
    if bare.ends_with(".local") || bare.ends_with(".home.arpa") {
        return EndpointLocality::PrivateNetwork;
    }
    EndpointLocality::Remote
}

fn classify_ip(ip: IpAddr) -> EndpointLocality {
    match ip {
        IpAddr::V4(v4) => classify_v4(v4),
        IpAddr::V6(v6) => {
            if let Some(mapped) = v6.to_ipv4_mapped() {
                return classify_v4(mapped);
            }
            classify_v6(v6)
        }
    }
}

fn classify_v4(v4: Ipv4Addr) -> EndpointLocality {
    if v4.is_loopback() {
        EndpointLocality::Loopback
    } else if v4.is_private() || v4.is_link_local() {
        EndpointLocality::PrivateNetwork
    } else {
        // Includes 0.0.0.0: a client "connecting" there is not a
        // well-defined local endpoint, so fail closed.
        EndpointLocality::Remote
    }
}

fn classify_v6(v6: Ipv6Addr) -> EndpointLocality {
    let first = v6.segments()[0];
    if v6.is_loopback() {
        EndpointLocality::Loopback
    } else if (first & 0xfe00) == 0xfc00 || (first & 0xffc0) == 0xfe80 {
        // fc00::/7 unique-local, fe80::/10 link-local.
        EndpointLocality::PrivateNetwork
    } else {
        EndpointLocality::Remote
    }
}

/// Classify a URL by its host. Unparsable or host-less URLs are remote.
pub fn classify_endpoint(url: &str) -> EndpointLocality {
    reqwest::Url::parse(url.trim())
        .ok()
        .and_then(|parsed| parsed.host_str().map(classify_host))
        .unwrap_or(EndpointLocality::Remote)
}

/// Host component of a URL, without credentials, path, or query.
///
/// Used in user-facing messages so configured URLs with embedded userinfo
/// never leak into logs.
pub fn endpoint_host(url: &str) -> Option<String> {
    let parsed = reqwest::Url::parse(url.trim()).ok()?;
    let host = parsed.host_str()?;
    Some(match parsed.port() {
        Some(port) => format!("{host}:{port}"),
        None => host.to_string(),
    })
}

/// URL without `user:password@`, for display. Unparsable input that could
/// hide credentials is replaced entirely.
pub fn redact_url_userinfo(url: &str) -> String {
    if let Ok(mut parsed) = reqwest::Url::parse(url.trim()) {
        if parsed.has_host() {
            if parsed.username().is_empty() && parsed.password().is_none() {
                return url.to_string();
            }
            let _ = parsed.set_username("");
            let _ = parsed.set_password(None);
            return parsed.to_string().trim_end_matches('/').to_string();
        }
    }
    // Host-less or unparsable input: hide it if it could carry credentials.
    if url.contains('@') {
        "(unparsable URL)".to_string()
    } else {
        url.to_string()
    }
}

/// Provider id safe to display: redacts credentials embedded in
/// `custom:` / `anthropic-custom:` URLs.
pub fn display_provider_id(name: &str) -> String {
    for prefix in ["custom:", "anthropic-custom:"] {
        if let Some(url) = name.trim().strip_prefix(prefix) {
            return format!("{prefix}{}", redact_url_userinfo(url));
        }
    }
    name.trim().to_string()
}

/// How an inference target was resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InferenceTargetKind {
    /// A self-hostable server whose base URL is known (llama.cpp, Ollama, ...).
    Endpoint,
    /// A provider with a fixed hosted endpoint.
    Hosted,
    /// A local CLI binary that forwards prompts to a hosted service.
    HostedCli,
}

/// The endpoint a provider id would use, and its locality.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InferenceTarget {
    pub provider: String,
    pub kind: InferenceTargetKind,
    /// Base URL for [`InferenceTargetKind::Endpoint`] targets.
    pub endpoint: Option<String>,
    pub locality: EndpointLocality,
}

/// Default base URL for self-hostable providers, mirroring the factory.
pub fn self_hosted_default_base_url(name: &str) -> Option<&'static str> {
    match name {
        "llamacpp" | "llama.cpp" => Some(LLAMACPP_DEFAULT_BASE_URL),
        "lmstudio" | "lm-studio" => Some(LMSTUDIO_DEFAULT_BASE_URL),
        "ollama" => Some(OLLAMA_DEFAULT_BASE_URL),
        "sglang" => Some(SGLANG_DEFAULT_BASE_URL),
        "vllm" => Some(VLLM_DEFAULT_BASE_URL),
        "osaurus" => Some(OSAURUS_DEFAULT_BASE_URL),
        "litellm" | "lite-llm" => Some(LITELLM_DEFAULT_BASE_URL),
        _ => None,
    }
}

fn non_empty(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

/// Resolve the endpoint the provider factory would use for `name`.
///
/// `api_url` is the base URL override passed to the factory. Mirrors the
/// factory's URL handling: providers that ignore `api_url` (LM Studio, fixed
/// hosted APIs) are classified by the URL they actually call.
pub fn resolve_inference_target(name: &str, api_url: Option<&str>) -> InferenceTarget {
    let name = name.trim();
    let endpoint_target = |endpoint: &str| InferenceTarget {
        provider: name.to_string(),
        kind: InferenceTargetKind::Endpoint,
        endpoint: Some(endpoint.to_string()),
        locality: classify_endpoint(endpoint),
    };

    if let Some(url) = name
        .strip_prefix("custom:")
        .or_else(|| name.strip_prefix("anthropic-custom:"))
    {
        return endpoint_target(url);
    }

    match name {
        "ollama" => {
            let env_url = std::env::var("rain_PROVIDER_URL").ok();
            let url = non_empty(env_url.as_deref())
                .or(non_empty(api_url))
                .unwrap_or(OLLAMA_DEFAULT_BASE_URL);
            endpoint_target(url)
        }
        // The factory ignores api_url for LM Studio.
        "lmstudio" | "lm-studio" => endpoint_target(LMSTUDIO_DEFAULT_BASE_URL),
        "llamacpp" | "llama.cpp" | "sglang" | "vllm" | "osaurus" | "litellm" | "lite-llm" => {
            let default = self_hosted_default_base_url(name).unwrap_or(LLAMACPP_DEFAULT_BASE_URL);
            endpoint_target(non_empty(api_url).unwrap_or(default))
        }
        "openai" => endpoint_target(non_empty(api_url).unwrap_or("https://api.openai.com/v1")),
        "claude-code" | "gemini-cli" | "kilocli" | "kilo" => InferenceTarget {
            provider: name.to_string(),
            kind: InferenceTargetKind::HostedCli,
            endpoint: None,
            locality: EndpointLocality::Remote,
        },
        _ => InferenceTarget {
            provider: name.to_string(),
            kind: InferenceTargetKind::Hosted,
            endpoint: None,
            locality: EndpointLocality::Remote,
        },
    }
}

/// Refusal raised when `privacy = "local"` meets a non-local inference target.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error(
    "privacy mode 'local' refuses inference provider '{provider}' ({reason}). \
     Use a loopback or private-network endpoint (llama.cpp, Ollama, LM Studio), \
     or set [rig] privacy = \"hybrid\" to allow hosted inference explicitly."
)]
pub struct LocalInferenceViolation {
    pub provider: String,
    pub reason: String,
}

/// Enforce local-only inference for one provider construction.
pub fn check_local_inference(
    name: &str,
    api_url: Option<&str>,
) -> Result<InferenceTarget, LocalInferenceViolation> {
    let target = resolve_inference_target(name, api_url);
    if target.locality.is_local() {
        return Ok(target);
    }
    let reason = match target.kind {
        InferenceTargetKind::HostedCli => "CLI wrapper for a hosted service".to_string(),
        InferenceTargetKind::Hosted => "hosted service".to_string(),
        InferenceTargetKind::Endpoint => match target.endpoint.as_deref().and_then(endpoint_host) {
            Some(host) => format!("endpoint host {host} is not loopback or private-network"),
            None => "endpoint URL is not a valid local URL".to_string(),
        },
    };
    Err(LocalInferenceViolation {
        provider: display_provider_id(name),
        reason,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_host_covers_loopback_private_and_remote() {
        for host in [
            "localhost",
            "127.0.0.1",
            "127.8.9.10",
            "::1",
            "[::1]",
            "api.localhost",
        ] {
            assert_eq!(classify_host(host), EndpointLocality::Loopback, "{host}");
        }
        for host in [
            "10.0.0.5",
            "172.16.4.2",
            "192.168.1.20",
            "169.254.3.3",
            "fd00::1",
            "fe80::1",
            "rig-node.local",
            "lab.home.arpa",
        ] {
            assert_eq!(
                classify_host(host),
                EndpointLocality::PrivateNetwork,
                "{host}"
            );
        }
        for host in [
            "0.0.0.0",
            "8.8.8.8",
            "api.openai.com",
            "example.com",
            "2001:4860::1",
            "localhost.example.com",
        ] {
            assert_eq!(classify_host(host), EndpointLocality::Remote, "{host}");
        }
    }

    #[test]
    fn classify_endpoint_fails_closed_on_garbage() {
        assert_eq!(classify_endpoint("not a url"), EndpointLocality::Remote);
        assert_eq!(classify_endpoint(""), EndpointLocality::Remote);
        assert_eq!(
            classify_endpoint("http://[::ffff:127.0.0.1]:8080/v1"),
            EndpointLocality::Loopback
        );
    }

    #[test]
    fn llamacpp_target_uses_existing_default_and_alias() {
        for name in ["llamacpp", "llama.cpp"] {
            let target = resolve_inference_target(name, None);
            assert_eq!(target.endpoint.as_deref(), Some(LLAMACPP_DEFAULT_BASE_URL));
            assert_eq!(target.endpoint.as_deref(), Some("http://localhost:8080/v1"));
            assert_eq!(target.locality, EndpointLocality::Loopback);
        }
        let lan = resolve_inference_target("llamacpp", Some("http://192.168.1.7:8080/v1"));
        assert_eq!(lan.locality, EndpointLocality::PrivateNetwork);
        let remote = resolve_inference_target("llamacpp", Some("https://gpu.example.com/v1"));
        assert_eq!(remote.locality, EndpointLocality::Remote);
    }

    #[test]
    fn lmstudio_ignores_api_url_like_the_factory() {
        let target = resolve_inference_target("lmstudio", Some("https://example.com/v1"));
        assert_eq!(target.endpoint.as_deref(), Some(LMSTUDIO_DEFAULT_BASE_URL));
        assert!(target.locality.is_local());
    }

    #[test]
    fn hosted_and_cli_wrapper_providers_are_remote() {
        for name in ["openrouter", "anthropic", "groq", "gemini", "bedrock"] {
            let target = resolve_inference_target(name, None);
            assert_eq!(target.kind, InferenceTargetKind::Hosted, "{name}");
            assert!(!target.locality.is_local());
        }
        for name in ["claude-code", "gemini-cli", "kilocli"] {
            let target = resolve_inference_target(name, None);
            assert_eq!(target.kind, InferenceTargetKind::HostedCli, "{name}");
            assert!(!target.locality.is_local());
        }
        assert!(!resolve_inference_target("openai", None).locality.is_local());
        assert!(
            resolve_inference_target("openai", Some("http://127.0.0.1:9000/v1"))
                .locality
                .is_local()
        );
    }

    #[test]
    fn custom_provider_urls_are_classified() {
        assert!(
            resolve_inference_target("custom:http://127.0.0.1:5000/v1", None)
                .locality
                .is_local()
        );
        assert!(
            !resolve_inference_target("anthropic-custom:https://proxy.example.com", None)
                .locality
                .is_local()
        );
    }

    #[test]
    fn display_helpers_redact_credentials() {
        assert_eq!(
            redact_url_userinfo("http://user:secret@10.0.0.2:8000/v1"),
            "http://10.0.0.2:8000/v1"
        );
        assert_eq!(
            redact_url_userinfo("http://localhost:8000/v1"),
            "http://localhost:8000/v1"
        );
        assert_eq!(redact_url_userinfo("user:pw@nowhere"), "(unparsable URL)");
        assert_eq!(
            display_provider_id("custom:https://u:key@api.example.com/v1"),
            "custom:https://api.example.com/v1"
        );
        assert_eq!(display_provider_id("openrouter"), "openrouter");
        let error = check_local_inference("custom:https://u:key@api.example.com/v1", None)
            .unwrap_err()
            .to_string();
        assert!(!error.contains("key@"), "{error}");
    }

    #[test]
    fn check_local_inference_reports_host_without_credentials() {
        let error =
            check_local_inference("llamacpp", Some("https://user:secret@gpu.example.com/v1"))
                .unwrap_err();
        let rendered = error.to_string();
        assert!(rendered.contains("gpu.example.com"), "{rendered}");
        assert!(!rendered.contains("secret"), "{rendered}");
        assert!(check_local_inference("llamacpp", None).is_ok());
        assert!(check_local_inference("lmstudio", None).is_ok());
        assert!(check_local_inference("openrouter", None).is_err());
    }
}
