//! Skybridge — EXPERIMENTAL low-bandwidth plaintext transport.
//!
//! Skybridge is an isolated extension, not part of the stable core. This
//! build supports software operation only:
//!
//! - [`frame`]: frame codec and CRC-16/X.25 integrity check
//! - [`fec`]: Hamming(7,4) forward error correction with interleaving
//! - [`fragment`]: split messages over several frames and reassemble them
//! - [`modem`]: continuous-phase BFSK baseband modem (in-memory samples)
//! - [`wav`]: PCM16 WAV files for development and testing
//! - [`radio`]: RF transmit backend interface, permanently disabled here
//! - [`SkybridgeTransport`]: transport adapter writing/reading baseband
//!   audio to files or memory — never to a radio
//!
//! Receive pipeline: samples → demodulate (FEC) → frame decode + CRC →
//! reassembly → [`InboundMessage`] → [`inbox::admit`](crate::rig::inbox::admit).

pub mod fec;
pub mod fragment;
pub mod frame;
pub mod modem;
pub mod radio;
pub mod wav;

use crate::rig::action::AuthorizedAction;
use crate::rig::capability::{CapabilityState, CapabilityStatus, TransportDetail};
use crate::rig::inbox::InboundMessage;
use crate::rig::transport::{RigTransport, SendReceipt, TransportError, check_send};
use async_trait::async_trait;
use fragment::MAX_MESSAGE_BYTES;
use frame::{Frame, StationId};
use modem::{ModemConfig, ModemError};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

/// Transport capabilities of Skybridge.
pub fn skybridge_detail() -> TransportDetail {
    TransportDetail {
        bidirectional: true,
        max_payload_bytes: MAX_MESSAGE_BYTES,
        send_supported: true,
        rf_transmit: radio::active_backend().can_transmit(),
    }
}

/// Capability status: software baseband is always present; RF never is.
pub fn skybridge_status() -> CapabilityStatus {
    CapabilityStatus::new(
        "skybridge",
        CapabilityState::Available,
        "experimental · software baseband to WAV/memory only · RF transmit disabled",
    )
    .with_transport(skybridge_detail())
}

/// Where modulated samples go. There is no RF variant.
#[derive(Debug, Clone)]
pub enum BasebandSink {
    WavFile(PathBuf),
    Memory(Arc<Mutex<Vec<Vec<f32>>>>),
}

/// Where received samples come from.
#[derive(Debug, Clone)]
pub enum BasebandSource {
    WavFile(PathBuf),
    Memory(Arc<Mutex<VecDeque<Vec<f32>>>>),
}

/// Skybridge transport adapter (software baseband only).
#[derive(Debug)]
pub struct SkybridgeTransport {
    modem: ModemConfig,
    station: StationId,
    sequence: Mutex<u16>,
    sink: Option<BasebandSink>,
    source: Mutex<Option<BasebandSource>>,
    /// Messages decoded from a recording but not yet returned.
    pending: Mutex<VecDeque<InboundMessage>>,
}

impl SkybridgeTransport {
    pub fn new(station: StationId, modem: ModemConfig) -> Self {
        Self {
            modem,
            station,
            sequence: Mutex::new(0),
            sink: None,
            source: Mutex::new(None),
            pending: Mutex::new(VecDeque::new()),
        }
    }

    #[must_use]
    pub fn with_sink(mut self, sink: BasebandSink) -> Self {
        self.sink = Some(sink);
        self
    }

    #[must_use]
    pub fn with_source(self, source: BasebandSource) -> Self {
        if let Ok(mut slot) = self.source.lock() {
            *slot = Some(source);
        }
        self
    }

    pub fn modem(&self) -> &ModemConfig {
        &self.modem
    }

    /// Reserve `count` consecutive sequence numbers.
    fn reserve_sequence(&self, count: usize) -> Result<u16, TransportError> {
        let mut sequence = self
            .sequence
            .lock()
            .map_err(|_| TransportError::Io("sequence lock poisoned".into()))?;
        let current = *sequence;
        *sequence = sequence.wrapping_add(u16::try_from(count).unwrap_or(u16::MAX));
        Ok(current)
    }

    /// Frames and baseband samples for one message (fragments back to back).
    pub fn render(&self, payload: &[u8]) -> Result<(Vec<Frame>, Vec<f32>), TransportError> {
        let malformed =
            |error: &dyn std::fmt::Display| TransportError::Malformed(error.to_string());
        let parts = fragment::split(
            std::str::from_utf8(payload).map_err(|_| malformed(&"payload is not UTF-8 text"))?,
        )
        .len();
        let frames = fragment::fragment(&self.station, self.reserve_sequence(parts)?, payload)
            .map_err(|error| malformed(&error))?;
        let mut samples = Vec::new();
        for frame in &frames {
            let bytes = frame.encode().map_err(|error| malformed(&error))?;
            samples
                .extend(modem::modulate(&self.modem, &bytes).map_err(|error| malformed(&error))?);
        }
        Ok((frames, samples))
    }

    fn next_samples(&self) -> Result<Option<Vec<f32>>, TransportError> {
        let mut slot = self
            .source
            .lock()
            .map_err(|_| TransportError::Io("source lock poisoned".into()))?;
        match slot.as_ref() {
            None => Err(TransportError::Unsupported(
                "skybridge: no baseband source configured".into(),
            )),
            Some(BasebandSource::Memory(queue)) => Ok(queue
                .lock()
                .map_err(|_| TransportError::Io("baseband queue poisoned".into()))?
                .pop_front()),
            Some(BasebandSource::WavFile(path)) => {
                let (samples, rate) =
                    wav::read_file(path).map_err(|error| TransportError::Io(error.to_string()))?;
                if rate != self.modem.sample_rate {
                    return Err(TransportError::Malformed(format!(
                        "WAV sample rate {rate} Hz does not match modem rate {} Hz",
                        self.modem.sample_rate
                    )));
                }
                // A file holds one recording: after it is read, the source
                // becomes an empty in-memory queue (drained, not missing).
                *slot = Some(BasebandSource::Memory(Arc::new(
                    Mutex::new(VecDeque::new()),
                )));
                Ok(Some(samples))
            }
        }
    }
}

#[async_trait]
impl RigTransport for SkybridgeTransport {
    fn id(&self) -> &'static str {
        "skybridge"
    }

    fn capabilities(&self) -> TransportDetail {
        skybridge_detail()
    }

    async fn status(&self) -> CapabilityStatus {
        skybridge_status()
    }

    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError> {
        check_send(self, action)?;
        let Some(sink) = &self.sink else {
            return Err(TransportError::Unsupported(
                "skybridge: no baseband sink configured".into(),
            ));
        };
        let (_, samples) = self.render(action.payload())?;
        match sink {
            BasebandSink::WavFile(path) => wav::write_file(path, &samples, self.modem.sample_rate)
                .map_err(|error| TransportError::Io(error.to_string()))?,
            BasebandSink::Memory(buffer) => buffer
                .lock()
                .map_err(|_| TransportError::Io("baseband buffer poisoned".into()))?
                .push(samples),
        }
        Ok(SendReceipt {
            transport: "skybridge".into(),
            proposal_id: action.proposal_id().to_string(),
            bytes: action.payload().len(),
        })
    }

    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError> {
        let pending_lock = || TransportError::Io("skybridge pending queue poisoned".into());
        if let Some(message) = self.pending.lock().map_err(|_| pending_lock())?.pop_front() {
            return Ok(Some(message));
        }
        let Some(samples) = self.next_samples()? else {
            return Ok(None);
        };
        let messages = decode_messages(&self.modem, &samples)?;
        let mut pending = self.pending.lock().map_err(|_| pending_lock())?;
        pending.extend(messages);
        Ok(pending.pop_front())
    }
}

/// Demodulate a recording and reassemble complete messages, in order.
/// Incomplete multi-frame messages are dropped.
pub fn decode_messages(
    modem: &ModemConfig,
    samples: &[f32],
) -> Result<Vec<InboundMessage>, TransportError> {
    let frames: Vec<Frame> = match modem::demodulate_all(modem, samples) {
        Ok(found) => found.into_iter().map(|d| d.frame).collect(),
        Err(ModemError::NoFrame) => return Ok(Vec::new()),
        Err(error) => return Err(TransportError::Malformed(error.to_string())),
    };
    let reassembly = fragment::reassemble(&frames);
    if reassembly.dropped_frames > 0 {
        tracing::warn!(
            dropped = reassembly.dropped_frames,
            "skybridge: dropped frames of incomplete messages"
        );
    }
    Ok(reassembly
        .messages
        .into_iter()
        .map(|message| InboundMessage {
            transport: "skybridge".into(),
            source: message.station.as_str().to_string(),
            payload: message.payload,
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::action::{
        ActionBoundary, ActionKind, ActionPolicy, ActionProposal, Disposition, ProposalOrigin,
    };
    use crate::rig::inbox::{InboundRequest, InboxDisposition, admit};

    fn boundary() -> ActionBoundary {
        ActionBoundary::new(
            ActionPolicy::new(MAX_MESSAGE_BYTES).allow_transport("skybridge"),
            None,
        )
    }

    fn proposal(origin: ProposalOrigin, text: &str) -> ActionProposal {
        ActionProposal::new(
            origin,
            ActionKind::TransportSend {
                transport: "skybridge".into(),
                destination: None,
            },
            text,
        )
    }

    #[tokio::test]
    async fn baseband_loop_through_memory_reaches_the_restricted_inbox() {
        let buffer = Arc::new(Mutex::new(Vec::new()));
        let station = StationId::parse("N0CALL").unwrap();
        let tx = SkybridgeTransport::new(station.clone(), ModemConfig::default())
            .with_sink(BasebandSink::Memory(buffer.clone()));
        let token = boundary()
            .submit(proposal(ProposalOrigin::Operator, "!shell reboot"), None)
            .1
            .unwrap();
        tx.send(&token).await.unwrap();

        let queue: VecDeque<Vec<f32>> = buffer.lock().unwrap().drain(..).collect();
        let rx = SkybridgeTransport::new(station, ModemConfig::default())
            .with_source(BasebandSource::Memory(Arc::new(Mutex::new(queue))));
        let message = rx.receive().await.unwrap().unwrap();
        assert_eq!(message.source, "N0CALL");
        match admit(&message) {
            InboxDisposition::Admitted { request, .. } => assert_eq!(
                request,
                InboundRequest::Note {
                    text: "!shell reboot".into()
                }
            ),
            other @ InboxDisposition::Rejected { .. } => panic!("{other:?}"),
        }
        assert!(rx.receive().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn wav_file_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("frame.wav");
        let station = StationId::parse("RIG-1").unwrap();
        let tx = SkybridgeTransport::new(station.clone(), ModemConfig::default())
            .with_sink(BasebandSink::WavFile(path.clone()));
        let token = boundary()
            .submit(proposal(ProposalOrigin::Operator, "PING"), None)
            .1
            .unwrap();
        tx.send(&token).await.unwrap();
        let rx = SkybridgeTransport::new(station, ModemConfig::default())
            .with_source(BasebandSource::WavFile(path));
        let message = rx.receive().await.unwrap().unwrap();
        assert_eq!(message.payload, b"PING");
        assert!(
            rx.receive().await.unwrap().is_none(),
            "file source is consumed once"
        );
    }

    #[tokio::test]
    async fn model_proposals_cannot_reach_the_modem_without_approval() {
        let (record, token) = boundary().submit(proposal(ProposalOrigin::Model, "hello"), None);
        assert_eq!(record.disposition, Disposition::AwaitingHumanAuthorization);
        assert!(token.is_none());
    }

    #[test]
    fn status_reports_experimental_software_only() {
        let status = skybridge_status();
        assert!(status.experimental);
        let detail = status.transport.unwrap();
        assert!(!detail.rf_transmit);
        assert_eq!(detail.max_payload_bytes, MAX_MESSAGE_BYTES);
    }

    #[tokio::test]
    async fn long_message_is_fragmented_and_reassembled_from_one_recording() {
        let buffer = Arc::new(Mutex::new(Vec::new()));
        let station = StationId::parse("N0CALL").unwrap();
        let sender = SkybridgeTransport::new(station.clone(), ModemConfig::default())
            .with_sink(BasebandSink::Memory(buffer.clone()));
        let long = "coherence log entry; ".repeat(30);
        assert!(long.len() > frame::MAX_PAYLOAD * 3);
        let short = "PING";
        for text in [long.as_str(), short] {
            let token = boundary()
                .submit(proposal(ProposalOrigin::Operator, text), None)
                .1
                .unwrap();
            sender.send(&token).await.unwrap();
        }
        // Both messages in a single recording.
        let recording: Vec<f32> = buffer.lock().unwrap().concat();
        let receiver = SkybridgeTransport::new(station, ModemConfig::default()).with_source(
            BasebandSource::Memory(Arc::new(Mutex::new(VecDeque::from([recording])))),
        );
        let first = receiver.receive().await.unwrap().unwrap();
        assert_eq!(first.payload, long.as_bytes());
        let second = receiver.receive().await.unwrap().unwrap();
        assert_eq!(second.payload, short.as_bytes());
        assert!(receiver.receive().await.unwrap().is_none());
    }

    #[tokio::test]
    async fn oversized_payload_is_refused_before_modulation() {
        let big = "x".repeat(MAX_MESSAGE_BYTES + 1);
        let (record, token) = ActionBoundary::new(
            ActionPolicy::new(MAX_MESSAGE_BYTES).allow_transport("skybridge"),
            None,
        )
        .submit(proposal(ProposalOrigin::Operator, &big), None);
        assert_eq!(record.disposition, Disposition::Rejected);
        assert!(token.is_none());
    }
}
