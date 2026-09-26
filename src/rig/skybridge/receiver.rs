//! Receive-only baseband input from an external receiver or SDR command.
//!
//! The operator configures an argv (never run through a shell) whose
//! stdout is raw signed 16-bit little-endian mono PCM at the modem sample
//! rate, for example `rtl_fm -f 14.1M -M usb -s 8000 -`. R.A.I.N. only
//! reads that stream: nothing here writes to a device, keys a transmitter,
//! or selects a frequency. Capture is bounded in time and size, and the
//! process is killed when capture ends.

use super::modem::MAX_DEMOD_SAMPLES;
use crate::rig::transport::TransportError;
use std::time::Duration;
use tokio::io::AsyncReadExt;

/// Longest single capture.
pub const MAX_LISTEN_SECS: u64 = 300;

fn io(detail: impl std::fmt::Display) -> TransportError {
    TransportError::Io(format!("receiver: {detail}"))
}

/// Run `argv` for up to `seconds` and return the samples it produced.
pub async fn capture(
    argv: &[String],
    seconds: u64,
    sample_rate: u32,
) -> Result<Vec<f32>, TransportError> {
    let (program, args) = argv
        .split_first()
        .filter(|(program, _)| !program.trim().is_empty())
        .ok_or_else(|| io("no receive command configured"))?;
    if seconds == 0 || seconds > MAX_LISTEN_SECS {
        return Err(io(format!("capture must be 1-{MAX_LISTEN_SECS} seconds")));
    }
    let wanted_samples = usize::try_from(seconds * u64::from(sample_rate))
        .unwrap_or(usize::MAX)
        .min(MAX_DEMOD_SAMPLES);
    let wanted_bytes = wanted_samples * 2;

    let mut child = tokio::process::Command::new(program)
        .args(args)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| io(format!("cannot start {program}: {error}")))?;
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| io("no stdout from receive command"))?;

    let mut bytes = Vec::with_capacity(wanted_bytes.min(1 << 20));
    let deadline = tokio::time::Instant::now() + Duration::from_secs(seconds);
    let mut chunk = vec![0u8; 16 * 1024];
    while bytes.len() < wanted_bytes {
        let read = tokio::time::timeout_at(deadline, stdout.read(&mut chunk)).await;
        match read {
            Err(_) | Ok(Ok(0)) => break,
            Ok(Ok(n)) => {
                let take = n.min(wanted_bytes - bytes.len());
                bytes.extend_from_slice(&chunk[..take]);
            }
            Ok(Err(error)) => return Err(io(error)),
        }
    }
    drop(stdout);
    // The command may still be running (a live receiver); stop it.
    let _ = child.start_kill();
    let status = child.wait().await.map_err(io)?;
    if bytes.is_empty() && !status.success() && status.code().is_some() {
        return Err(io(format!(
            "{program} exited with {status} and produced no audio"
        )));
    }
    Ok(bytes
        .chunks_exact(2)
        .map(|pair| f32::from(i16::from_le_bytes([pair[0], pair[1]])) / 32768.0)
        .collect())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn sh(script: &str) -> Vec<String> {
        vec!["sh".into(), "-c".into(), script.into()]
    }

    #[tokio::test]
    async fn reads_pcm16_le_from_the_command() {
        let samples = capture(&sh("printf '\\000\\100\\000\\300'"), 1, 8_000)
            .await
            .unwrap();
        assert_eq!(samples, vec![0.5, -0.5]);
    }

    #[tokio::test]
    async fn capture_is_bounded_and_the_process_is_stopped() {
        let started = std::time::Instant::now();
        let samples = capture(&sh("cat /dev/zero"), 1, 8_000).await.unwrap();
        assert_eq!(samples.len(), 8_000);
        assert!(started.elapsed() < Duration::from_secs(5));

        // A silent receiver ends at the time limit.
        let started = std::time::Instant::now();
        let samples = capture(&sh("sleep 30"), 1, 8_000).await.unwrap();
        assert!(samples.is_empty());
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[tokio::test]
    async fn failing_or_missing_commands_are_errors() {
        let error = capture(&sh("exit 7"), 1, 8_000).await.unwrap_err();
        assert!(error.to_string().contains("exited"), "{error}");
        let missing = vec!["/nonexistent/rtl_fm".to_string()];
        assert!(capture(&missing, 1, 8_000).await.is_err());
        assert!(capture(&[], 1, 8_000).await.is_err());
        assert!(capture(&sh("true"), 0, 8_000).await.is_err());
        assert!(
            capture(&sh("true"), MAX_LISTEN_SECS + 1, 8_000)
                .await
                .is_err()
        );
    }
}
