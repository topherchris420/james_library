use std::sync::Arc;

pub trait AdvisoryPublisher: Send + Sync {
    fn publish(&self, response: &str);
}

#[derive(Default)]
pub struct NoopAdvisoryPublisher;

impl AdvisoryPublisher for NoopAdvisoryPublisher {
    fn publish(&self, _response: &str) {}
}

#[cfg(feature = "p2p")]
pub struct P2pAdvisoryPublisher;

#[cfg(feature = "p2p")]
impl AdvisoryPublisher for P2pAdvisoryPublisher {
    fn publish(&self, response: &str) {
        let Some(sanitized) = sanitize_for_p2p(response) else {
            return;
        };
        tokio::spawn(async move {
            crate::p2p::publish_advisory_result(&sanitized).await;
        });
    }
}

pub fn build_publisher() -> Arc<dyn AdvisoryPublisher> {
    #[cfg(feature = "p2p")]
    {
        if p2p_enabled() {
            return Arc::new(P2pAdvisoryPublisher);
        }
    }

    Arc::new(NoopAdvisoryPublisher)
}

#[cfg(feature = "p2p")]
fn p2p_enabled() -> bool {
    std::env::var("ZEROCLAW_P2P_ENABLE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

#[cfg(not(feature = "p2p"))]
fn p2p_enabled() -> bool {
    false
}

#[cfg(feature = "p2p")]
fn sanitize_for_p2p(response: &str) -> Option<String> {
    const MAX_LEN: usize = 512;
    let lower = response.to_ascii_lowercase();
    let blocked = [
        "api_key",
        "token",
        "password",
        "secret",
        "bearer",
        "credential",
    ];
    if blocked.iter().any(|k| lower.contains(k)) {
        return None;
    }

    let trimmed = response.trim();
    if trimmed.is_empty() {
        return None;
    }

    let mut out = String::new();
    for ch in trimmed.chars().take(MAX_LEN) {
        out.push(ch);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(feature = "p2p")]
    #[test]
    fn sanitize_blocks_sensitive_keywords() {
        assert!(sanitize_for_p2p("token=abcd").is_none());
    }

    #[cfg(feature = "p2p")]
    #[test]
    fn sanitize_limits_output_size() {
        let input = "x".repeat(600);
        let output = sanitize_for_p2p(&input).expect("sanitized output expected");
        assert_eq!(output.len(), 512);
    }
}
