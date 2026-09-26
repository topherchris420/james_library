//! RF transmit backends.
//!
//! RF transmit is off unless the binary is built with the `rig-rf-transmit`
//! Cargo feature (not in the default build). Independent guards:
//!
//! 1. The action boundary rejects every `RadioTransmit` proposal in default
//!    builds. With the feature, it authorizes only operator proposals with
//!    the configured licensed callsign, an in-band frequency, a power within
//!    the configured limit, and an interactive human confirmation for that
//!    exact proposal. Models and host code can never obtain a token.
//! 2. [`transmit_backend`] returns [`DisabledRfBackend`], which refuses every
//!    call, unless the feature is compiled in *and* `[rig.radio]` configures
//!    a callsign, a power limit and transmit commands.
//! 3. Every backend refuses a token that does not authorize radio transmit.
//!
//! The only real backend, `ExternalCommandRfBackend`, runs operator-
//! configured argv commands (no shell): key the transmitter, play the
//! rendered WAV, and always unkey afterwards. R.A.I.N. has no radio drivers
//! of its own.

use crate::config::RigRadioConfig;
use crate::rig::action::AuthorizedAction;
use std::path::Path;

/// Longest single transmission.
pub const MAX_TX_AIRTIME_SECS: u64 = 180;

/// RF transmit failure.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum RadioError {
    #[error("RF transmit is disabled: {0}")]
    TransmitDisabled(&'static str),
    #[error("authorization does not cover radio transmit")]
    NotRadioAuthorization,
    #[error("transmission would last {secs} s; limit is {MAX_TX_AIRTIME_SECS} s")]
    TooLong { secs: u64 },
    #[error("transmit command failed: {0}")]
    Command(String),
}

/// Interface a transmit backend implements.
pub trait RfTransmitBackend: Send + Sync {
    fn name(&self) -> &'static str;

    /// Whether the backend can emit RF at all.
    fn can_transmit(&self) -> bool;

    /// Transmit baseband samples. Requires a radio-transmit authorization.
    fn transmit(&self, samples: &[f32], authorization: &AuthorizedAction)
    -> Result<(), RadioError>;
}

/// Refuses everything.
#[derive(Debug, Clone, Copy)]
pub struct DisabledRfBackend {
    reason: &'static str,
}

impl DisabledRfBackend {
    pub fn reason(&self) -> &'static str {
        self.reason
    }
}

impl RfTransmitBackend for DisabledRfBackend {
    fn name(&self) -> &'static str {
        "none"
    }

    fn can_transmit(&self) -> bool {
        false
    }

    fn transmit(
        &self,
        _samples: &[f32],
        authorization: &AuthorizedAction,
    ) -> Result<(), RadioError> {
        if authorization.radio_transmit().is_none() {
            return Err(RadioError::NotRadioAuthorization);
        }
        Err(RadioError::TransmitDisabled(self.reason))
    }
}

/// Why transmit is unavailable, or `None` when a backend can be built.
pub fn transmit_unavailable(radio: Option<&RigRadioConfig>) -> Option<&'static str> {
    if !crate::rig::action::RF_TRANSMIT_COMPILED {
        return Some("not compiled into this build (Cargo feature rig-rf-transmit)");
    }
    let Some(radio) = radio else {
        return Some("no [rig.radio] settings");
    };
    if radio.callsign.is_none() || radio.max_power_w.is_none() {
        return Some("[rig.radio] callsign and max_power_w are required");
    }
    if radio.transmit.is_none() {
        return Some("no [rig.radio.transmit] commands configured");
    }
    None
}

/// The transmit backend for this build and configuration. `work_dir` holds
/// the temporary WAV handed to the play command.
pub fn transmit_backend(
    radio: Option<&RigRadioConfig>,
    work_dir: &Path,
) -> Box<dyn RfTransmitBackend> {
    if let Some(reason) = transmit_unavailable(radio) {
        return Box::new(DisabledRfBackend { reason });
    }
    #[cfg(feature = "rig-rf-transmit")]
    if let Some(transmit) = radio.and_then(|radio| radio.transmit.clone()) {
        return Box::new(external::ExternalCommandRfBackend::new(
            transmit,
            work_dir.to_path_buf(),
            super::modem::ModemConfig::default().sample_rate,
        ));
    }
    let _ = work_dir;
    Box::new(DisabledRfBackend {
        reason: "no transmit backend available",
    })
}

#[cfg(feature = "rig-rf-transmit")]
pub mod external {
    //! Transmit through operator-configured external commands.

    use super::{MAX_TX_AIRTIME_SECS, RadioError, RfTransmitBackend};
    use crate::config::RigRadioTransmitConfig;
    use crate::rig::action::AuthorizedAction;
    use std::path::PathBuf;
    use std::time::{Duration, Instant};

    const PTT_TIMEOUT: Duration = Duration::from_secs(10);
    const PLAY_GRACE: Duration = Duration::from_secs(15);

    #[derive(Debug, Clone)]
    pub struct ExternalCommandRfBackend {
        commands: RigRadioTransmitConfig,
        work_dir: PathBuf,
        sample_rate: u32,
    }

    impl ExternalCommandRfBackend {
        pub fn new(commands: RigRadioTransmitConfig, work_dir: PathBuf, sample_rate: u32) -> Self {
            Self {
                commands,
                work_dir,
                sample_rate,
            }
        }
    }

    fn substitute(argv: &[String], values: &[(&str, String)]) -> Vec<String> {
        argv.iter()
            .map(|arg| {
                values
                    .iter()
                    .fold(arg.clone(), |acc, (key, value)| acc.replace(key, value))
            })
            .collect()
    }

    /// Run argv to completion within `timeout`; kill it otherwise.
    fn run(label: &str, argv: &[String], timeout: Duration) -> Result<(), RadioError> {
        let Some((program, args)) = argv.split_first() else {
            return Ok(());
        };
        let mut child = std::process::Command::new(program)
            .args(args)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .spawn()
            .map_err(|error| {
                RadioError::Command(format!("{label}: cannot start {program}: {error}"))
            })?;
        let deadline = Instant::now() + timeout;
        loop {
            match child.try_wait() {
                Ok(Some(status)) if status.success() => return Ok(()),
                Ok(Some(status)) => {
                    return Err(RadioError::Command(format!(
                        "{label}: {program} exited with {status}"
                    )));
                }
                Ok(None) if Instant::now() >= deadline => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(RadioError::Command(format!(
                        "{label}: {program} timed out after {}s",
                        timeout.as_secs()
                    )));
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(20)),
                Err(error) => return Err(RadioError::Command(format!("{label}: {error}"))),
            }
        }
    }

    impl RfTransmitBackend for ExternalCommandRfBackend {
        fn name(&self) -> &'static str {
            "external-command"
        }

        fn can_transmit(&self) -> bool {
            true
        }

        fn transmit(
            &self,
            samples: &[f32],
            authorization: &AuthorizedAction,
        ) -> Result<(), RadioError> {
            let (_, frequency_hz, power_w) = authorization
                .radio_transmit()
                .ok_or(RadioError::NotRadioAuthorization)?;
            let airtime = (samples.len() as u64).div_ceil(u64::from(self.sample_rate.max(1)));
            if airtime > MAX_TX_AIRTIME_SECS {
                return Err(RadioError::TooLong { secs: airtime });
            }
            std::fs::create_dir_all(&self.work_dir)
                .map_err(|error| RadioError::Command(format!("work dir: {error}")))?;
            let wav = self
                .work_dir
                .join(format!("skybridge-tx-{}.wav", authorization.proposal_id()));
            crate::rig::skybridge::wav::write_file(&wav, samples, self.sample_rate).map_err(
                |error| RadioError::Command(format!("writing {}: {error}", wav.display())),
            )?;
            let values = [
                ("{wav}", wav.display().to_string()),
                ("{frequency_hz}", frequency_hz.to_string()),
                ("{power_w}", power_w.to_string()),
            ];
            let ptt_on = substitute(&self.commands.ptt_on, &values);
            let play = substitute(&self.commands.play, &values);
            let ptt_off = substitute(&self.commands.ptt_off, &values);

            let keyed = run("ptt_on", &ptt_on, PTT_TIMEOUT);
            let played = keyed
                .as_ref()
                .map_err(Clone::clone)
                .and_then(|()| run("play", &play, Duration::from_secs(airtime) + PLAY_GRACE));
            // Unkey whatever happened above.
            let unkeyed = run("ptt_off", &ptt_off, PTT_TIMEOUT);
            let _ = std::fs::remove_file(&wav);
            played.and(unkeyed)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionKind, ActionPolicy, ActionProposal, ProposalOrigin,
    };

    fn send_token() -> AuthorizedAction {
        let boundary =
            ActionBoundary::new(ActionPolicy::new(256).allow_transport("skybridge"), None);
        let proposal = ActionProposal::new(
            ProposalOrigin::Operator,
            ActionKind::TransportSend {
                transport: "skybridge".into(),
                destination: None,
            },
            "hello",
        );
        boundary.submit(proposal, None).1.unwrap()
    }

    #[test]
    fn transmit_is_disabled_without_complete_settings() {
        let dir = tempfile::tempdir().unwrap();
        let backend = transmit_backend(None, dir.path());
        assert_eq!(backend.name(), "none");
        assert!(!backend.can_transmit());
        let partial = RigRadioConfig {
            callsign: Some("N0CALL".into()),
            ..RigRadioConfig::default()
        };
        assert!(transmit_unavailable(Some(&partial)).is_some());
        assert!(!transmit_backend(Some(&partial), dir.path()).can_transmit());
    }

    #[cfg(not(feature = "rig-rf-transmit"))]
    #[test]
    fn default_build_never_transmits_even_when_configured() {
        let dir = tempfile::tempdir().unwrap();
        let radio = RigRadioConfig {
            callsign: Some("N0CALL".into()),
            max_power_w: Some(10),
            transmit: Some(crate::config::RigRadioTransmitConfig {
                play: vec!["true".into()],
                ..Default::default()
            }),
            ..RigRadioConfig::default()
        };
        let reason = transmit_unavailable(Some(&radio)).unwrap();
        assert!(reason.contains("not compiled"));
        assert!(!transmit_backend(Some(&radio), dir.path()).can_transmit());
    }

    #[test]
    fn backends_refuse_tokens_for_other_actions() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(
            transmit_backend(None, dir.path()).transmit(&[0.0; 8], &send_token()),
            Err(RadioError::NotRadioAuthorization)
        );
    }

    #[cfg(all(unix, feature = "rig-rf-transmit"))]
    mod external_commands {
        use super::*;
        use crate::config::RigRadioTransmitConfig;
        use crate::rig::action::{HumanApproval, RadioPolicy};

        fn radio_token() -> AuthorizedAction {
            let boundary = ActionBoundary::new(
                ActionPolicy::new(256).with_radio(RadioPolicy {
                    licensed_callsign: "N0CALL".into(),
                    max_power_w: 20,
                }),
                None,
            );
            let proposal = ActionProposal::new(
                ProposalOrigin::Operator,
                ActionKind::RadioTransmit {
                    callsign: "N0CALL".into(),
                    frequency_hz: 14_100_000,
                    power_w: 5,
                },
                "CQ",
            );
            let approval = HumanApproval::confirmed_by_operator(&proposal.id);
            boundary.submit(proposal, Some(&approval)).1.unwrap()
        }

        fn sh(script: &str) -> Vec<String> {
            vec!["sh".into(), "-c".into(), script.into(), "rig".into()]
        }

        fn configured(dir: &Path, play: Vec<String>) -> (RigRadioConfig, PathBuf) {
            let log = dir.join("log");
            let append = |what: &str| sh(&format!("echo {what} $1 >> {}", log.display()));
            let mut ptt_on = append("on");
            ptt_on.push("{frequency_hz}:{power_w}".into());
            let radio = RigRadioConfig {
                callsign: Some("N0CALL".into()),
                max_power_w: Some(20),
                transmit: Some(RigRadioTransmitConfig {
                    ptt_on,
                    play,
                    ptt_off: append("off"),
                }),
                ..RigRadioConfig::default()
            };
            (radio, log)
        }

        use std::path::PathBuf;

        #[test]
        fn keys_plays_and_always_unkeys() {
            let dir = tempfile::tempdir().unwrap();
            let log_path = dir.path().join("log");
            let play = sh(&format!(
                "test -s \"$1\" && echo play >> {}",
                log_path.display()
            ));
            let mut play = play;
            play.push("{wav}".into());
            let (radio, log) = configured(dir.path(), play);
            let backend = transmit_backend(Some(&radio), &dir.path().join("tx"));
            assert_eq!(backend.name(), "external-command");
            backend.transmit(&[0.1; 800], &radio_token()).unwrap();
            let lines = std::fs::read_to_string(log).unwrap();
            assert_eq!(lines, "on 14100000:5\nplay\noff\n");
            assert_eq!(std::fs::read_dir(dir.path().join("tx")).unwrap().count(), 0);
        }

        #[test]
        fn failed_play_still_unkeys() {
            let dir = tempfile::tempdir().unwrap();
            let (radio, log) = configured(dir.path(), sh("exit 4"));
            let backend = transmit_backend(Some(&radio), dir.path());
            let error = backend.transmit(&[0.1; 800], &radio_token()).unwrap_err();
            assert!(error.to_string().contains("play"), "{error}");
            let lines = std::fs::read_to_string(log).unwrap();
            assert!(lines.ends_with("off\n"), "{lines}");
        }

        #[test]
        fn failed_key_skips_play_but_unkeys() {
            let dir = tempfile::tempdir().unwrap();
            let (mut radio, log) = configured(dir.path(), sh("echo play >> /dev/null"));
            radio.transmit.as_mut().unwrap().ptt_on = sh("exit 1");
            let backend = transmit_backend(Some(&radio), dir.path());
            assert!(backend.transmit(&[0.1; 800], &radio_token()).is_err());
            assert_eq!(std::fs::read_to_string(log).unwrap(), "off\n");
        }

        #[test]
        fn overlong_transmissions_and_wrong_tokens_are_refused() {
            let dir = tempfile::tempdir().unwrap();
            let (radio, log) = configured(dir.path(), sh("true"));
            let backend = transmit_backend(Some(&radio), dir.path());
            let seconds = usize::try_from(MAX_TX_AIRTIME_SECS).unwrap() + 1;
            let samples = vec![0.0; 8_000 * seconds];
            assert!(matches!(
                backend.transmit(&samples, &radio_token()),
                Err(RadioError::TooLong { .. })
            ));
            assert_eq!(
                backend.transmit(&[0.0; 8], &send_token()),
                Err(RadioError::NotRadioAuthorization)
            );
            assert!(!log.exists(), "nothing was keyed");
        }
    }
}
