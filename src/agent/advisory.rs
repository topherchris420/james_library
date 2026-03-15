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
pub struct P2pAdvisoryPublisher {
    p2p_config: crate::config::schema::P2pConfig,
}

#[cfg(feature = "p2p")]
impl AdvisoryPublisher for P2pAdvisoryPublisher {
    fn publish(&self, response: &str) {
        let Some(sanitized) = crate::p2p::sanitize_for_advisory(response) else {
            return;
        };
        let cfg = self.p2p_config.clone();
        tokio::spawn(async move {
            crate::p2p::publish_advisory_result(&cfg, &sanitized).await;
        });
    }
}

pub fn build_publisher(config: &crate::config::Config) -> Arc<dyn AdvisoryPublisher> {
    #[cfg(feature = "p2p")]
    {
        if crate::p2p::p2p_enabled(&config.p2p) {
            return Arc::new(P2pAdvisoryPublisher {
                p2p_config: config.p2p.clone(),
            });
        }
    }

    let _ = config; // suppress unused warning when p2p feature is off
    Arc::new(NoopAdvisoryPublisher)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(feature = "p2p")]
    #[test]
    fn sanitize_blocks_sensitive_keywords() {
        assert!(crate::p2p::sanitize_for_advisory("token=abcd").is_none());
    }

    #[cfg(feature = "p2p")]
    #[test]
    fn sanitize_limits_output_size() {
        let input = "x".repeat(600);
        let output = crate::p2p::sanitize_for_advisory(&input).expect("sanitized output expected");
        assert_eq!(output.len(), 512);
    }
}
