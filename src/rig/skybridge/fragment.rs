//! Fragmentation and reassembly of Skybridge messages longer than one frame.
//!
//! A message is split at UTF-8 character boundaries into frames of at most
//! [`MAX_PAYLOAD`] bytes with consecutive sequence numbers. Every frame but
//! the first carries the `continuation` flag and only the last carries
//! `final`, so a single-frame message is `final` without `continuation`.
//! Every fragment is valid plaintext on its own, so each frame passes the
//! codec's checks independently.
//!
//! Reassembly accepts a run that starts with a non-continuation frame,
//! continues with frames from the same station with consecutive sequence
//! numbers (wrapping), and ends in a `final` frame. Anything else (a gap, a
//! station change, an orphaned continuation, a run without an end, or too
//! many fragments) is dropped and counted; partial messages are never
//! delivered.

use super::frame::{Frame, FrameError, MAX_PAYLOAD, StationId};

/// Largest message Skybridge carries (five full frames).
pub const MAX_MESSAGE_BYTES: usize = 1000;
/// Largest number of fragments per message.
pub const MAX_FRAGMENTS: usize = MAX_MESSAGE_BYTES.div_ceil(MAX_PAYLOAD);

/// Split `text` into fragments of at most [`MAX_PAYLOAD`] bytes without
/// breaking a UTF-8 character.
pub fn split(text: &str) -> Vec<&str> {
    let mut parts = Vec::new();
    let mut rest = text;
    while rest.len() > MAX_PAYLOAD {
        let mut cut = MAX_PAYLOAD;
        while !rest.is_char_boundary(cut) {
            cut -= 1;
        }
        let (head, tail) = rest.split_at(cut);
        parts.push(head);
        rest = tail;
    }
    parts.push(rest);
    parts
}

/// Build the frames for one message starting at `first_sequence`.
pub fn fragment(
    station: &StationId,
    first_sequence: u16,
    payload: &[u8],
) -> Result<Vec<Frame>, FrameError> {
    if payload.len() > MAX_MESSAGE_BYTES {
        return Err(FrameError::PayloadTooLarge {
            len: payload.len(),
            max: MAX_MESSAGE_BYTES,
        });
    }
    let text = std::str::from_utf8(payload)
        .map_err(|_| FrameError::NotPlaintext("payload is not UTF-8 text".into()))?;
    let parts = split(text);
    let last = parts.len() - 1;
    parts
        .into_iter()
        .enumerate()
        .map(|(index, part)| {
            let offset = u16::try_from(index).unwrap_or(u16::MAX);
            let mut frame = Frame::new(
                station.clone(),
                first_sequence.wrapping_add(offset),
                part.as_bytes(),
            )?;
            frame.final_fragment = index == last;
            frame.continuation = index > 0;
            Ok(frame)
        })
        .collect()
}

/// A reassembled message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Message {
    pub station: StationId,
    pub first_sequence: u16,
    pub fragments: usize,
    pub payload: Vec<u8>,
}

/// Result of reassembling a sequence of received frames.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Reassembly {
    pub messages: Vec<Message>,
    /// Frames discarded because their message was incomplete or invalid.
    pub dropped_frames: usize,
}

/// Reassemble frames in reception order.
pub fn reassemble(frames: &[Frame]) -> Reassembly {
    let mut result = Reassembly::default();
    let mut run: Vec<&Frame> = Vec::new();
    for frame in frames {
        if frame.continuation {
            let continues = run.last().is_some_and(|last| {
                last.station == frame.station && last.sequence.wrapping_add(1) == frame.sequence
            });
            if !continues {
                result.dropped_frames += run.len() + 1;
                run.clear();
                continue;
            }
        } else {
            result.dropped_frames += run.len();
            run.clear();
        }
        run.push(frame);
        let size: usize = run.iter().map(|f| f.payload.len()).sum();
        if run.len() > MAX_FRAGMENTS || size > MAX_MESSAGE_BYTES {
            result.dropped_frames += run.len();
            run.clear();
            continue;
        }
        if frame.final_fragment {
            result.messages.push(Message {
                station: run[0].station.clone(),
                first_sequence: run[0].sequence,
                fragments: run.len(),
                payload: run.iter().flat_map(|f| f.payload.iter().copied()).collect(),
            });
            run.clear();
        }
    }
    result.dropped_frames += run.len();
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn station(id: &str) -> StationId {
        StationId::parse(id).unwrap()
    }

    #[test]
    fn short_message_is_one_final_frame() {
        let frames = fragment(&station("N0CALL"), 9, b"PING").unwrap();
        assert_eq!(frames.len(), 1);
        assert!(frames[0].final_fragment);
    }

    #[test]
    fn long_message_splits_on_char_boundaries_and_reassembles() {
        // 3-byte characters force cuts that are not at MAX_PAYLOAD exactly.
        let text = "résonance ✓ ".repeat(40);
        assert!(text.len() > MAX_PAYLOAD * 2 && text.len() <= MAX_MESSAGE_BYTES);
        let frames = fragment(&station("N0CALL"), u16::MAX, text.as_bytes()).unwrap();
        assert!(frames.len() >= 3);
        assert!(frames.iter().all(|f| f.payload.len() <= MAX_PAYLOAD));
        assert!(frames.iter().rev().skip(1).all(|f| !f.final_fragment));
        assert!(!frames[0].continuation && frames.iter().skip(1).all(|f| f.continuation));
        assert_eq!(frames[1].sequence, 0, "sequence wraps");
        let result = reassemble(&frames);
        assert_eq!(result.dropped_frames, 0);
        assert_eq!(result.messages.len(), 1);
        assert_eq!(result.messages[0].payload, text.as_bytes());
    }

    #[test]
    fn oversized_messages_are_refused() {
        let text = "x".repeat(MAX_MESSAGE_BYTES + 1);
        assert!(fragment(&station("N0CALL"), 0, text.as_bytes()).is_err());
    }

    #[test]
    fn gaps_station_changes_and_missing_final_drop_partial_messages() {
        let text = "y".repeat(MAX_PAYLOAD * 3);
        let frames = fragment(&station("N0CALL"), 0, text.as_bytes()).unwrap();
        // Missing middle fragment: the lone final fragment is not a message.
        let gapped = vec![frames[0].clone(), frames[2].clone()];
        let result = reassemble(&gapped);
        assert!(result.messages.is_empty());
        assert_eq!(result.dropped_frames, 2);
        let result = reassemble(&frames[2..]);
        assert!(result.messages.is_empty());

        // Another station's final frame cannot complete this run.
        let mut other = frames[1].clone();
        other.station = station("K1ABC");
        other.final_fragment = true;
        let result = reassemble(&[frames[0].clone(), other]);
        assert!(result.messages.is_empty());

        // No final frame.
        let result = reassemble(&frames[..2]);
        assert!(result.messages.is_empty());
        assert_eq!(result.dropped_frames, 2);

        // A complete message after junk is still delivered.
        let mut stream = vec![frames[1].clone()];
        stream.extend(fragment(&station("K1ABC"), 5, b"PING").unwrap());
        let result = reassemble(&stream);
        assert_eq!(result.messages.len(), 1);
        assert_eq!(result.messages[0].payload, b"PING");
        assert_eq!(result.dropped_frames, 1);
    }

    #[test]
    fn too_many_fragments_are_dropped() {
        let station = station("N0CALL");
        let last = u16::try_from(MAX_FRAGMENTS).unwrap();
        let mut frames: Vec<Frame> = (0..=last)
            .map(|seq| {
                let mut frame = Frame::new(station.clone(), seq, b"z").unwrap();
                frame.final_fragment = false;
                frame.continuation = seq > 0;
                frame
            })
            .collect();
        frames.last_mut().unwrap().final_fragment = true;
        let result = reassemble(&frames);
        assert!(result.messages.is_empty());
        assert_eq!(result.dropped_frames, frames.len());
    }
}
