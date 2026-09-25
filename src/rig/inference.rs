//! Local inference discovery for llama.cpp, Ollama, LM Studio, and the
//! configured default provider.
//!
//! This module only *observes*. Provider construction, request handling and
//! credentials stay in `crate::providers`; model-list parsing reuses the
//! onboarding catalog parsers. Remote endpoints are never probed.

use super::capability::{CapabilityState, CapabilityStatus, InferenceDetail};
use super::context::{RigContext, selected_provider};
use super::probe::ProbeOutcome;
use crate::onboard::wizard::{
    parse_ollama_model_ids, parse_openai_compatible_model_ids, resolve_live_models_endpoint,
};
use crate::providers::locality::{
    EndpointLocality, InferenceTargetKind, classify_endpoint, display_provider_id,
    redact_url_userinfo, resolve_inference_target,
};

use std::fmt::Write as _;

const NOT_PROBED: &str = "remote endpoint; the Rig never probes remote services";

fn is_selected(ctx: &RigContext, aliases: &[&str]) -> bool {
    aliases.contains(&selected_provider(&ctx.config).as_str())
}

fn binary_on_path(names: &[&str]) -> bool {
    names.iter().any(|name| which::which(name).is_ok())
}

/// Credential the runtime would send for this provider (value never reported).
fn provider_credential(ctx: &RigContext, provider: &str, selected: bool) -> Option<String> {
    let override_key = if selected {
        ctx.config.api_key.as_deref()
    } else {
        None
    };
    crate::providers::resolve_provider_credential(provider, override_key)
}

fn count_label(count: usize, noun: &str) -> String {
    if count == 1 {
        format!("1 {noun}")
    } else {
        format!("{count} {noun}s")
    }
}

fn unreachable_detail(base: &str, binary: bool, binary_name: &str, start_hint: &str) -> String {
    let base = redact_url_userinfo(base);
    if binary {
        format!(
            "not reachable at {base}; {binary_name} is installed but not running ({start_hint})"
        )
    } else {
        format!("not reachable at {base}")
    }
}

fn state_for_unreachable(selected: bool) -> CapabilityState {
    if selected {
        CapabilityState::Configured
    } else {
        CapabilityState::Unavailable
    }
}

fn auth_rejected(outcome: &ProbeOutcome) -> bool {
    matches!(outcome.status(), Some(401 | 403))
}

/// Probe llama.cpp `llama-server`: `/health` for readiness and the
/// OpenAI-compatible `/v1/models` listing for discovered models.
pub async fn probe_llamacpp(ctx: &RigContext) -> CapabilityStatus {
    let selected = is_selected(ctx, &["llamacpp", "llama.cpp"]);
    let base = ctx.endpoints.llamacpp.trim_end_matches('/').to_string();
    let locality = classify_endpoint(&base);
    let credential = provider_credential(ctx, "llamacpp", selected);
    let mut detail = InferenceDetail {
        provider: "llamacpp".into(),
        endpoint: Some(redact_url_userinfo(&base)),
        locality: locality.label().into(),
        auth_configured: credential.is_some(),
        selected,
        binary_on_path: binary_on_path(&["llama-server"]),
        ..InferenceDetail::default()
    };

    if !locality.is_local() {
        let state = state_for_unreachable(selected);
        return CapabilityStatus::new("llamacpp", state, NOT_PROBED).with_inference(detail);
    }

    let root = base.strip_suffix("/v1").unwrap_or(&base).to_string();
    let models_url = resolve_live_models_endpoint("llamacpp", Some(&base))
        .unwrap_or_else(|| format!("{base}/models"));
    let health_url = format!("{root}/health");
    let (health, models) = tokio::join!(
        ctx.probe.get(&health_url, credential.as_deref()),
        ctx.probe.get(&models_url, credential.as_deref()),
    );
    detail.probed = true;

    if !health.is_reachable() && !models.is_reachable() {
        let text = unreachable_detail(
            &base,
            detail.binary_on_path,
            "llama-server",
            "start llama-server -m <model.gguf>",
        );
        return CapabilityStatus::new("llamacpp", state_for_unreachable(selected), text)
            .with_inference(detail);
    }
    if auth_rejected(&models) {
        let text = "reachable, but the server rejected the credential; set LLAMACPP_API_KEY to the server's --api-key";
        return CapabilityStatus::new("llamacpp", CapabilityState::Degraded, text)
            .with_inference(detail);
    }
    // llama-server answers 503 on /health while the model is still loading.
    if health.status() == Some(503) {
        return CapabilityStatus::new(
            "llamacpp",
            CapabilityState::Degraded,
            "reachable, model still loading (/health returned 503)",
        )
        .with_inference(detail);
    }
    match models.ok_json() {
        Some(body) => {
            detail.models = parse_openai_compatible_model_ids(body);
            let text = format!(
                "ready · {} · {}",
                count_label(detail.models.len(), "model"),
                locality.label()
            );
            CapabilityStatus::new("llamacpp", CapabilityState::Running, text).with_inference(detail)
        }
        None => {
            let text = match models.status() {
                Some(code) => format!("reachable, but /v1/models returned HTTP {code}"),
                None => "reachable, but /v1/models did not respond".into(),
            };
            CapabilityStatus::new("llamacpp", CapabilityState::Degraded, text)
                .with_inference(detail)
        }
    }
}

/// Probe Ollama's native `/api/tags` listing.
pub async fn probe_ollama(ctx: &RigContext) -> CapabilityStatus {
    let selected = is_selected(ctx, &["ollama"]);
    let base = ctx.endpoints.ollama.trim_end_matches('/').to_string();
    let base = base.strip_suffix("/api").unwrap_or(&base).to_string();
    let locality = classify_endpoint(&base);
    let credential = provider_credential(ctx, "ollama", selected);
    let mut detail = InferenceDetail {
        provider: "ollama".into(),
        endpoint: Some(redact_url_userinfo(&base)),
        locality: locality.label().into(),
        auth_configured: credential.is_some(),
        selected,
        binary_on_path: binary_on_path(&["ollama"]),
        ..InferenceDetail::default()
    };
    if !locality.is_local() {
        let state = state_for_unreachable(selected);
        return CapabilityStatus::new("ollama", state, NOT_PROBED).with_inference(detail);
    }

    // Local Ollama is keyless; never forward a credential to it.
    let tags = ctx.probe.get(&format!("{base}/api/tags"), None).await;
    detail.probed = true;
    match (&tags, tags.ok_json()) {
        (_, Some(body)) => {
            let (hosted, local): (Vec<String>, Vec<String>) = parse_ollama_model_ids(body)
                .into_iter()
                .partition(|model| model.ends_with(":cloud"));
            detail.models = local;
            detail.hosted_models = hosted;
            let mut text = format!(
                "ready · {} · {}",
                count_label(detail.models.len(), "local model"),
                locality.label()
            );
            if !detail.hosted_models.is_empty() {
                let _ = write!(
                    text,
                    " · {} routed to Ollama cloud (hosted)",
                    count_label(detail.hosted_models.len(), "model")
                );
            }
            CapabilityStatus::new("ollama", CapabilityState::Running, text).with_inference(detail)
        }
        (ProbeOutcome::Unreachable { .. }, None) => {
            let text =
                unreachable_detail(&base, detail.binary_on_path, "ollama", "run `ollama serve`");
            CapabilityStatus::new("ollama", state_for_unreachable(selected), text)
                .with_inference(detail)
        }
        (outcome, None) => {
            let text = format!(
                "reachable, but /api/tags returned HTTP {}",
                outcome.status().unwrap_or_default()
            );
            CapabilityStatus::new("ollama", CapabilityState::Degraded, text).with_inference(detail)
        }
    }
}

/// Probe LM Studio's OpenAI-compatible `/v1/models` listing.
pub async fn probe_lmstudio(ctx: &RigContext) -> CapabilityStatus {
    let selected = is_selected(ctx, &["lmstudio", "lm-studio"]);
    let base = ctx.endpoints.lmstudio.trim_end_matches('/').to_string();
    let locality = classify_endpoint(&base);
    let mut detail = InferenceDetail {
        provider: "lmstudio".into(),
        endpoint: Some(base.clone()),
        locality: locality.label().into(),
        auth_configured: false,
        selected,
        binary_on_path: binary_on_path(&["lms"]),
        ..InferenceDetail::default()
    };
    if !locality.is_local() {
        let state = state_for_unreachable(selected);
        return CapabilityStatus::new("lmstudio", state, NOT_PROBED).with_inference(detail);
    }
    let models = ctx.probe.get(&format!("{base}/models"), None).await;
    detail.probed = true;
    match models.ok_json() {
        Some(body) => {
            detail.models = parse_openai_compatible_model_ids(body);
            let text = format!(
                "ready · {} · {}",
                count_label(detail.models.len(), "model"),
                locality.label()
            );
            CapabilityStatus::new("lmstudio", CapabilityState::Running, text).with_inference(detail)
        }
        None if models.is_reachable() => {
            let text = format!(
                "reachable, but /v1/models returned HTTP {}",
                models.status().unwrap_or_default()
            );
            CapabilityStatus::new("lmstudio", CapabilityState::Degraded, text)
                .with_inference(detail)
        }
        None => {
            let text = if detail.binary_on_path {
                format!("not detected at {base}; `lms` is installed (run `lms server start`)")
            } else {
                "not detected".to_string()
            };
            CapabilityStatus::new("lmstudio", state_for_unreachable(selected), text)
                .with_inference(detail)
        }
    }
}

/// Status for the configured default provider when it is not one of the
/// registered local servers. Self-hosted endpoints are probed if local;
/// hosted providers are reported as configured and never contacted.
pub async fn probe_configured_provider(ctx: &RigContext) -> Option<CapabilityStatus> {
    let provider = selected_provider(&ctx.config);
    if matches!(
        provider.as_str(),
        "llamacpp" | "llama.cpp" | "ollama" | "lmstudio" | "lm-studio"
    ) {
        return None;
    }
    let display = display_provider_id(&provider);
    let target = resolve_inference_target(&provider, ctx.config.api_url.as_deref());
    let credential = provider_credential(ctx, &provider, true);
    let mut detail = InferenceDetail {
        provider: display.clone(),
        endpoint: target.endpoint.clone().map(|url| redact_url_userinfo(&url)),
        locality: target.locality.label().into(),
        auth_configured: credential.is_some(),
        selected: true,
        ..InferenceDetail::default()
    };
    let status = match (target.kind, target.locality) {
        (InferenceTargetKind::HostedCli, _) => CapabilityStatus::configured_provider(
            &display,
            CapabilityState::Configured,
            "configured · local CLI wrapper for a hosted service · not probed",
        ),
        (InferenceTargetKind::Hosted, _) | (_, EndpointLocality::Remote) => {
            CapabilityStatus::configured_provider(
                &display,
                CapabilityState::Configured,
                "configured · hosted · not probed",
            )
        }
        (InferenceTargetKind::Endpoint, locality) => {
            let base = target.endpoint.clone().unwrap_or_default();
            let models_url = resolve_live_models_endpoint(&provider, Some(&base))
                .unwrap_or_else(|| format!("{}/models", base.trim_end_matches('/')));
            let outcome = ctx.probe.get(&models_url, credential.as_deref()).await;
            detail.probed = true;
            match outcome.ok_json() {
                Some(body) => {
                    detail.models = parse_openai_compatible_model_ids(body);
                    CapabilityStatus::configured_provider(
                        &display,
                        CapabilityState::Running,
                        format!(
                            "ready · {} · {}",
                            count_label(detail.models.len(), "model"),
                            locality.label()
                        ),
                    )
                }
                None if outcome.is_reachable() => CapabilityStatus::configured_provider(
                    &display,
                    CapabilityState::Degraded,
                    format!(
                        "reachable, but the model list returned HTTP {}",
                        outcome.status().unwrap_or_default()
                    ),
                ),
                None => CapabilityStatus::configured_provider(
                    &display,
                    CapabilityState::Configured,
                    format!(
                        "configured · not reachable at {}",
                        redact_url_userinfo(&base)
                    ),
                ),
            }
        }
    };
    Some(status.with_inference(detail))
}

/// Probe every inference capability concurrently.
pub async fn probe_all(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let (llamacpp, ollama, lmstudio, configured) = tokio::join!(
        probe_llamacpp(ctx),
        probe_ollama(ctx),
        probe_lmstudio(ctx),
        probe_configured_provider(ctx),
    );
    let mut statuses = vec![llamacpp, ollama, lmstudio];
    statuses.extend(configured);
    statuses
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::test_support::{context_with_endpoints, unreachable_url};
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    async fn llamacpp_server(models: &[&str]) -> MockServer {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(serde_json::json!({"status": "ok"})),
            )
            .mount(&server)
            .await;
        let data: Vec<_> = models
            .iter()
            .map(|id| serde_json::json!({"id": id, "object": "model", "owned_by": "llamacpp"}))
            .collect();
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(serde_json::json!({"object": "list", "data": data})),
            )
            .mount(&server)
            .await;
        server
    }

    #[tokio::test]
    async fn llamacpp_reachable_mock_reports_running_with_discovered_models() {
        let server = llamacpp_server(&["Qwen3-4B-Q4_K_M.gguf"]).await;
        let mut ctx = context_with_endpoints(Some(format!("{}/v1", server.uri())), None, None);
        ctx.config.default_provider = Some("llamacpp".into());
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Running, "{}", status.detail);
        let detail = status.inference.unwrap();
        assert_eq!(detail.models, vec!["Qwen3-4B-Q4_K_M.gguf".to_string()]);
        assert_eq!(detail.locality, "local");
        assert!(detail.selected);
        assert!(detail.probed);
    }

    #[tokio::test]
    async fn llamacpp_unreachable_is_unavailable_or_configured() {
        let mut ctx = context_with_endpoints(Some(unreachable_url("/v1")), None, None);
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Unavailable);
        assert!(status.detail.contains("not reachable"), "{}", status.detail);

        ctx.config.default_provider = Some("llama.cpp".into());
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Configured);
        assert!(status.inference.unwrap().selected);
    }

    #[tokio::test]
    async fn llamacpp_default_endpoint_is_the_existing_provider_default() {
        let endpoints = crate::rig::context::ProbeEndpoints::from_config(
            &crate::config::Config::default(),
            &crate::rig::context::RigEnv::default(),
        );
        assert_eq!(endpoints.llamacpp, "http://localhost:8080/v1");
        assert_eq!(
            endpoints.llamacpp,
            crate::providers::locality::LLAMACPP_DEFAULT_BASE_URL
        );
    }

    #[tokio::test]
    async fn llamacpp_auth_rejection_is_degraded_and_sends_configured_key() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .and(header("authorization", "Bearer rig-test-key"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"data": []})))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .respond_with(ResponseTemplate::new(401))
            .mount(&server)
            .await;

        let mut ctx = context_with_endpoints(Some(format!("{}/v1", server.uri())), None, None);
        ctx.config.default_provider = Some("llamacpp".into());
        ctx.config.api_key = Some("rig-test-key".into());
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Running, "{}", status.detail);
        assert!(status.inference.as_ref().unwrap().auth_configured);
        let serialized = serde_json::to_string(&status).unwrap();
        assert!(!serialized.contains("rig-test-key"), "credential leaked");

        ctx.config.api_key = Some("wrong".into());
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Degraded);
        assert!(status.detail.contains("LLAMACPP_API_KEY"));
    }

    #[tokio::test]
    async fn llamacpp_loading_model_is_degraded() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(503).set_body_json(
                serde_json::json!({"error": {"code": 503, "message": "Loading model"}}),
            ))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/v1/models"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&server)
            .await;
        let ctx = context_with_endpoints(Some(format!("{}/v1", server.uri())), None, None);
        let status = probe_llamacpp(&ctx).await;
        assert_eq!(status.state, CapabilityState::Degraded);
        assert!(status.detail.contains("loading"));
    }

    #[tokio::test]
    async fn remote_llamacpp_endpoint_is_never_probed() {
        let ctx = context_with_endpoints(Some("https://gpu.example.com/v1".into()), None, None);
        let status = probe_llamacpp(&ctx).await;
        let detail = status.inference.unwrap();
        assert!(!detail.probed);
        assert_eq!(detail.locality, "remote");
    }

    #[tokio::test]
    async fn ollama_mock_separates_cloud_models() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/api/tags"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "models": [{"name": "qwen3:4b"}, {"name": "minimax-m2.7:cloud"}]
            })))
            .mount(&server)
            .await;
        let ctx = context_with_endpoints(None, Some(server.uri()), None);
        let status = probe_ollama(&ctx).await;
        assert_eq!(status.state, CapabilityState::Running);
        let detail = status.inference.unwrap();
        assert_eq!(detail.models, vec!["qwen3:4b".to_string()]);
        assert_eq!(detail.hosted_models, vec!["minimax-m2.7:cloud".to_string()]);
    }

    #[tokio::test]
    async fn lmstudio_not_running_is_not_detected() {
        let ctx = context_with_endpoints(None, None, Some(unreachable_url("/v1")));
        let status = probe_lmstudio(&ctx).await;
        assert_eq!(status.state, CapabilityState::Unavailable);
    }

    #[tokio::test]
    async fn hosted_default_provider_is_configured_and_not_probed() {
        let mut ctx = crate::rig::test_support::context();
        ctx.config.default_provider = Some("openrouter".into());
        let status = probe_configured_provider(&ctx).await.unwrap();
        assert_eq!(status.state, CapabilityState::Configured);
        let detail = status.inference.unwrap();
        assert!(!detail.probed);
        assert_eq!(detail.locality, "remote");

        ctx.config.default_provider = Some("llamacpp".into());
        assert!(probe_configured_provider(&ctx).await.is_none());
    }

    #[tokio::test]
    async fn status_never_shows_url_credentials() {
        let port = crate::rig::test_support::unused_local_port();
        let ctx = context_with_endpoints(
            Some(format!("http://rig:hunter2@127.0.0.1:{port}/v1")),
            Some(format!("http://rig:hunter2@127.0.0.1:{port}")),
            None,
        );
        for status in [probe_llamacpp(&ctx).await, probe_ollama(&ctx).await] {
            let rendered = serde_json::to_string(&status).unwrap();
            assert!(
                !rendered.contains("hunter2"),
                "credential leaked: {rendered}"
            );
        }
    }
}
