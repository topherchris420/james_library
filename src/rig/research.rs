//! Research and decision capabilities: the R.A.I.N. Lab personas, the papers
//! corpus, the meeting's inference endpoint, and the bounded decision layer.
//!
//! These are observed from files and the documented environment contract of
//! the Python meeting (`RAIN_LLM_*`, `RAIN_DECISION_MODE`, ...). The Rig
//! never imports, launches, or reconfigures the meeting.

use super::capability::{CapabilityState, CapabilityStatus, InferenceDetail};
use super::context::RigContext;
use crate::onboard::wizard::parse_openai_compatible_model_ids;
use crate::providers::locality::{EndpointLocality, classify_endpoint_resolved};
use std::path::Path;

/// Base URL the meeting uses when neither `RAIN_LLM_BASE_URL` nor
/// `LM_STUDIO_BASE_URL` is set (see `Config.base_url` in
/// `rain_lab_meeting_chat_version.py`).
pub const MEETING_DEFAULT_BASE_URL: &str = "http://127.0.0.1:11434/v1";

/// Persona capability id and SOUL file for each research agent.
pub const RESEARCH_AGENTS: &[(&str, &str)] = &[
    ("james", "JAMES_SOUL.md"),
    ("jasmine", "JASMINE_SOUL.md"),
    ("luca", "LUCA_SOUL.md"),
    ("elena", "ELENA_SOUL.md"),
];

const LIBRARY_MISSING: &str =
    "research library not found; run from the james_library checkout or pass --library <path>";

/// Model the meeting uses when neither env nor `[rig.meeting]` pins one
/// (`DEFAULT_MODEL_NAME` in `rain_lab_meeting_chat_version.py`). It is an
/// Ollama cloud model, i.e. hosted inference.
pub const MEETING_DEFAULT_MODEL: &str = "minimax-m2.7:cloud";

/// Where a meeting setting came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SettingSource {
    /// `RAIN_LLM_*` / `LM_STUDIO_*` in the invoking shell.
    Environment,
    /// `[rig.meeting]` in `config.toml` (shared with the Python meeting).
    RigConfig,
    /// The meeting's built-in default.
    MeetingDefault,
}

impl SettingSource {
    pub fn label(self) -> &'static str {
        match self {
            Self::Environment => "environment",
            Self::RigConfig => "[rig.meeting]",
            Self::MeetingDefault => "meeting default",
        }
    }
}

/// Meeting inference settings, resolved like the Python meeting resolves
/// them: environment > `[rig.meeting]` > built-in default.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MeetingInference {
    pub base_url: String,
    pub base_url_source: SettingSource,
    pub model: String,
    pub model_source: SettingSource,
    pub endpoint_locality: EndpointLocality,
    /// Ollama `:cloud` models run on Ollama's hosted service even when the
    /// endpoint is a local Ollama daemon.
    pub hosted_model: bool,
}

impl MeetingInference {
    pub fn from_context(ctx: &RigContext) -> Self {
        let meeting = ctx.config.rig.meeting.as_ref();
        let pick = |env_keys: [&str; 2], configured: Option<&String>, default: &str| {
            if let Some(value) = env_keys.iter().find_map(|key| ctx.env.get(key)) {
                return (value.to_string(), SettingSource::Environment);
            }
            match configured.map(|v| v.trim()).filter(|v| !v.is_empty()) {
                Some(value) => (value.to_string(), SettingSource::RigConfig),
                None => (default.to_string(), SettingSource::MeetingDefault),
            }
        };
        let (base_url, base_url_source) = pick(
            ["RAIN_LLM_BASE_URL", "LM_STUDIO_BASE_URL"],
            meeting.and_then(|m| m.base_url.as_ref()),
            MEETING_DEFAULT_BASE_URL,
        );
        let base_url = base_url.trim_end_matches('/').to_string();
        let (model, model_source) = pick(
            ["RAIN_LLM_MODEL", "LM_STUDIO_MODEL"],
            meeting.and_then(|m| m.model.as_ref()),
            MEETING_DEFAULT_MODEL,
        );
        Self {
            endpoint_locality: classify_endpoint_resolved(&base_url),
            hosted_model: model.ends_with(":cloud"),
            base_url,
            base_url_source,
            model,
            model_source,
        }
    }

    /// Whether meeting prompts leave this machine / LAN.
    pub fn is_hosted(&self) -> bool {
        self.hosted_model || !self.endpoint_locality.is_local()
    }

    /// Whether any setting depends on the invoking shell's environment.
    pub fn uses_environment(&self) -> bool {
        self.base_url_source == SettingSource::Environment
            || self.model_source == SettingSource::Environment
    }
}

fn soul_file_present(root: &Path, file: &str) -> bool {
    std::fs::metadata(root.join(file)).is_ok_and(|meta| meta.is_file() && meta.len() > 0)
}

fn count_papers(root: &Path) -> Option<usize> {
    let entries = std::fs::read_dir(root.join("papers")).ok()?;
    Some(
        entries
            .filter_map(Result::ok)
            .filter(|entry| {
                !entry.file_name().to_string_lossy().starts_with('.')
                    && entry.file_type().is_ok_and(|kind| kind.is_file())
            })
            .count(),
    )
}

/// Research library, personas, and meeting endpoint.
pub async fn probe_research(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let mut statuses = Vec::new();
    match ctx.library_root.as_deref() {
        None => {
            statuses.push(CapabilityStatus::new(
                "research-registry",
                CapabilityState::Unavailable,
                LIBRARY_MISSING,
            ));
            for (id, _) in RESEARCH_AGENTS {
                statuses.push(CapabilityStatus::new(
                    id,
                    CapabilityState::Unavailable,
                    LIBRARY_MISSING,
                ));
            }
        }
        Some(root) => {
            statuses.push(match count_papers(root) {
                Some(count) => CapabilityStatus::new(
                    "research-registry",
                    CapabilityState::Available,
                    format!("{count} papers in papers/"),
                ),
                None => CapabilityStatus::new(
                    "research-registry",
                    CapabilityState::Unavailable,
                    "papers/ directory not found in the research library",
                ),
            });
            for (id, file) in RESEARCH_AGENTS {
                statuses.push(if soul_file_present(root, file) {
                    CapabilityStatus::new(id, CapabilityState::Available, *file)
                } else {
                    CapabilityStatus::new(
                        id,
                        CapabilityState::Unavailable,
                        format!("{file} missing or empty"),
                    )
                });
            }
        }
    }
    statuses.push(probe_meeting(ctx).await);
    statuses
}

async fn probe_meeting(ctx: &RigContext) -> CapabilityStatus {
    let meeting = MeetingInference::from_context(ctx);
    let model_label = format!("{} ({})", meeting.model, meeting.model_source.label());
    let locality = if meeting.is_hosted() {
        EndpointLocality::Remote
    } else {
        meeting.endpoint_locality
    };
    let mut detail = InferenceDetail {
        provider: "rain-lab-meeting".into(),
        endpoint: Some(crate::providers::locality::redact_url_userinfo(
            &meeting.base_url,
        )),
        locality: locality.label().into(),
        auth_configured: false,
        selected: false,
        models: vec![meeting.model.clone()],
        ..InferenceDetail::default()
    };
    if !meeting.endpoint_locality.is_local() {
        return CapabilityStatus::new(
            "lab-meeting",
            CapabilityState::Configured,
            format!("model {model_label} · hosted endpoint · not probed"),
        )
        .with_inference(detail);
    }
    let outcome = ctx
        .probe
        .get(&format!("{}/models", meeting.base_url), None)
        .await;
    detail.probed = true;
    let hosted_note = if meeting.hosted_model {
        " · model routed to Ollama cloud (hosted)"
    } else {
        ""
    };
    match outcome.ok_json() {
        Some(body) => {
            let served = parse_openai_compatible_model_ids(body);
            let model_state = if served.contains(&meeting.model) {
                ""
            } else {
                " · model not listed by the server"
            };
            CapabilityStatus::new(
                "lab-meeting",
                CapabilityState::Running,
                format!(
                    "ready · model {model_label} · {}{hosted_note}{model_state}",
                    meeting.endpoint_locality.label()
                ),
            )
            .with_inference(detail)
        }
        None => CapabilityStatus::new(
            "lab-meeting",
            CapabilityState::Unavailable,
            format!(
                "not reachable at {} (the offline demo still works){hosted_note}",
                crate::providers::locality::redact_url_userinfo(&meeting.base_url)
            ),
        )
        .with_inference(detail),
    }
}

/// Decision mode from `RAIN_DECISION_MODE` (default `off`).
fn decision_mode(ctx: &RigContext) -> Result<&'static str, String> {
    match ctx
        .env
        .get("RAIN_DECISION_MODE")
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        None | Some("off") => Ok("off"),
        Some("laya") => Ok("laya"),
        Some("jev") => Ok("jev"),
        Some("cascade") => Ok("cascade"),
        Some(other) => Err(other.to_string()),
    }
}

/// Whether Jev (TypeSafe) is enabled for routing or claim judgment.
pub fn jev_enabled(ctx: &RigContext) -> bool {
    matches!(decision_mode(ctx), Ok("jev" | "cascade"))
        || ctx
            .env
            .get("RAIN_JUDGMENT_PROVIDER")
            .is_some_and(|value| value.eq_ignore_ascii_case("typesafe"))
}

/// Deterministic validation, Laya, and Jev.
pub fn probe_decision(ctx: &RigContext) -> Vec<CapabilityStatus> {
    let mode = decision_mode(ctx);
    let validation = CapabilityStatus::new(
        "deterministic-validation",
        CapabilityState::Available,
        "compiled in · policy checks and deterministic validation gate every Rig action",
    );

    let laya = match &mode {
        Err(value) => CapabilityStatus::new(
            "laya",
            CapabilityState::Degraded,
            format!("unsupported RAIN_DECISION_MODE={value:?}; the meeting rejects it"),
        ),
        Ok("laya" | "cascade") => match ctx.env.get("RAIN_LAYA_CHECKPOINT") {
            Some(path) if Path::new(path).exists() => CapabilityStatus::new(
                "laya",
                CapabilityState::Configured,
                "checkpoint present · runs on demand in a timeout-bounded worker",
            ),
            Some(_) => CapabilityStatus::new(
                "laya",
                CapabilityState::Degraded,
                "RAIN_LAYA_CHECKPOINT points to a missing path; decisions hand off to R.A.I.N.",
            ),
            None => CapabilityStatus::new(
                "laya",
                CapabilityState::Degraded,
                "enabled, but RAIN_LAYA_CHECKPOINT is not set; decisions hand off to R.A.I.N.",
            ),
        },
        Ok(_) => CapabilityStatus::new(
            "laya",
            CapabilityState::Disabled,
            "RAIN_DECISION_MODE=off (default)",
        ),
    };

    let jev = if jev_enabled(ctx) {
        if ctx.env.is_set("TYPESAFE_API_KEY") {
            CapabilityStatus::new(
                "jev",
                CapabilityState::Configured,
                "enabled · remote service · each request still requires explicit consent",
            )
        } else {
            CapabilityStatus::new(
                "jev",
                CapabilityState::Degraded,
                "enabled, but TYPESAFE_API_KEY is not set; judgment reports UNAVAILABLE",
            )
        }
    } else {
        CapabilityStatus::new(
            "jev",
            CapabilityState::Disabled,
            "off (RAIN_DECISION_MODE / RAIN_JUDGMENT_PROVIDER not enabled)",
        )
    };
    vec![validation, laya, jev]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::context::RigEnv;
    use crate::rig::test_support::context;

    fn find<'a>(statuses: &'a [CapabilityStatus], id: &str) -> &'a CapabilityStatus {
        statuses.iter().find(|status| status.id == id).unwrap()
    }

    #[tokio::test]
    async fn missing_library_reports_agents_unavailable() {
        let mut ctx = context();
        ctx.library_root = None;
        ctx.env = RigEnv::from_pairs([(
            "RAIN_LLM_BASE_URL",
            crate::rig::test_support::unreachable_url("/v1"),
        )]);
        let statuses = probe_research(&ctx).await;
        assert_eq!(find(&statuses, "james").state, CapabilityState::Unavailable);
        assert_eq!(
            find(&statuses, "research-registry").state,
            CapabilityState::Unavailable
        );
        assert_eq!(
            find(&statuses, "lab-meeting").state,
            CapabilityState::Unavailable
        );
    }

    #[tokio::test]
    async fn library_personas_and_papers_are_available() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("rain_lab.py"), "").unwrap();
        for (_, file) in RESEARCH_AGENTS {
            std::fs::write(dir.path().join(file), "# soul").unwrap();
        }
        std::fs::create_dir(dir.path().join("papers")).unwrap();
        std::fs::write(dir.path().join("papers/a.md"), "paper").unwrap();
        std::fs::write(dir.path().join("papers/.hidden"), "x").unwrap();
        let mut ctx = context();
        ctx.library_root = Some(dir.path().to_path_buf());
        let statuses = probe_research(&ctx).await;
        for (id, _) in RESEARCH_AGENTS {
            assert_eq!(find(&statuses, id).state, CapabilityState::Available);
        }
        let registry = find(&statuses, "research-registry");
        assert_eq!(registry.state, CapabilityState::Available);
        assert_eq!(registry.detail, "1 papers in papers/");
    }

    #[test]
    fn meeting_cloud_model_is_hosted_even_on_loopback() {
        let mut ctx = context();
        ctx.env = RigEnv::from_pairs([("RAIN_LLM_MODEL", "minimax-m2.7:cloud")]);
        let meeting = MeetingInference::from_context(&ctx);
        assert_eq!(meeting.base_url, MEETING_DEFAULT_BASE_URL);
        assert_eq!(meeting.endpoint_locality, EndpointLocality::Loopback);
        assert!(meeting.is_hosted());

        ctx.env = RigEnv::from_pairs([("RAIN_LLM_MODEL", "qwen3:4b")]);
        assert!(!MeetingInference::from_context(&ctx).is_hosted());
        ctx.env = RigEnv::from_pairs([("RAIN_LLM_BASE_URL", "https://api.example.com/v1")]);
        assert!(MeetingInference::from_context(&ctx).is_hosted());
    }

    #[test]
    fn meeting_settings_precedence_env_then_rig_config_then_default() {
        let mut ctx = context();
        ctx.env = RigEnv::default();
        let unpinned = MeetingInference::from_context(&ctx);
        assert_eq!(unpinned.model, MEETING_DEFAULT_MODEL);
        assert_eq!(unpinned.model_source, SettingSource::MeetingDefault);
        assert!(
            unpinned.is_hosted(),
            "the built-in default is an Ollama cloud model"
        );

        ctx.config.rig.meeting = Some(crate::config::RigMeetingConfig {
            base_url: Some("http://127.0.0.1:8080/v1".into()),
            model: Some("Qwen3-4B-Q4_K_M.gguf".into()),
        });
        let pinned = MeetingInference::from_context(&ctx);
        assert_eq!(pinned.base_url, "http://127.0.0.1:8080/v1");
        assert_eq!(pinned.model_source, SettingSource::RigConfig);
        assert!(!pinned.is_hosted());
        assert!(!pinned.uses_environment());

        ctx.env = RigEnv::from_pairs([("RAIN_LLM_MODEL", "other.gguf")]);
        let overridden = MeetingInference::from_context(&ctx);
        assert_eq!(overridden.model, "other.gguf");
        assert_eq!(overridden.model_source, SettingSource::Environment);
        assert_eq!(overridden.base_url_source, SettingSource::RigConfig);
        assert!(overridden.uses_environment());
    }

    #[test]
    fn decision_layer_defaults_to_disabled_models() {
        let ctx = context();
        let statuses = probe_decision(&ctx);
        assert_eq!(
            find(&statuses, "deterministic-validation").state,
            CapabilityState::Available
        );
        assert_eq!(find(&statuses, "laya").state, CapabilityState::Disabled);
        assert_eq!(find(&statuses, "jev").state, CapabilityState::Disabled);
        assert!(!jev_enabled(&ctx));
    }

    #[test]
    fn decision_layer_reads_documented_env_contract() {
        let mut ctx = context();
        ctx.env = RigEnv::from_pairs([("RAIN_DECISION_MODE", "cascade")]);
        let statuses = probe_decision(&ctx);
        assert_eq!(find(&statuses, "laya").state, CapabilityState::Degraded);
        assert_eq!(find(&statuses, "jev").state, CapabilityState::Degraded);

        ctx.env = RigEnv::from_pairs([
            ("RAIN_JUDGMENT_PROVIDER", "typesafe"),
            ("TYPESAFE_API_KEY", "secret-value"),
        ]);
        let statuses = probe_decision(&ctx);
        let jev = find(&statuses, "jev");
        assert_eq!(jev.state, CapabilityState::Configured);
        assert!(!serde_json::to_string(jev).unwrap().contains("secret-value"));

        ctx.env = RigEnv::from_pairs([("RAIN_DECISION_MODE", "yolo")]);
        assert_eq!(
            find(&probe_decision(&ctx), "laya").state,
            CapabilityState::Degraded
        );
    }
}
