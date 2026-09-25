//! Skybridge frame codec and integrity check.
//!
//! Frame layout (version 1, all multi-byte fields big-endian):
//!
//! ```text
//! offset  size  field
//! 0       2     magic "SB" (0x53 0x42)
//! 2       1     version (1)
//! 3       1     flags: bit 0 = final fragment; bits 1-7 reserved, must be 0
//! 4       1     station id length N (1..=9)
//! 5       N     station id, ASCII [A-Z0-9/-]
//! 5+N     2     sequence number
//! 7+N     1     payload length L (0..=200)
//! 8+N     L     payload: UTF-8 plaintext (no control chars except \n and \t)
//! 8+N+L   2     CRC-16/X.25 over every preceding byte
//! ```
//!
//! Payloads are plaintext by design: there is no encryption or compression
//! field, and binary payloads are rejected. The CRC detects accidental
//! corruption only; it is not authentication.

use crate::rig::action::validate_plaintext;

pub const MAGIC: [u8; 2] = *b"SB";
pub const VERSION: u8 = 1;
pub const FLAG_FINAL: u8 = 0b0000_0001;
pub const MAX_STATION_LEN: usize = 9;
pub const MAX_PAYLOAD: usize = 200;
const HEADER_FIXED: usize = 8; // magic, version, flags, station len, seq, payload len
const CRC_LEN: usize = 2;
/// Largest encoded frame.
pub const MAX_FRAME_LEN: usize = HEADER_FIXED + MAX_STATION_LEN + MAX_PAYLOAD + CRC_LEN;

/// CRC-16/X.25 (HDLC/AX.25 FCS): reflected poly 0x1021, init/xorout 0xFFFF.
pub fn crc16_x25(bytes: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &byte in bytes {
        crc ^= u16::from(byte);
        for _ in 0..8 {
            crc = if crc & 1 != 0 {
                (crc >> 1) ^ 0x8408
            } else {
                crc >> 1
            };
        }
    }
    !crc
}

/// Codec failure.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FrameError {
    #[error("frame is truncated")]
    Truncated,
    #[error("bad magic bytes")]
    BadMagic,
    #[error("unsupported frame version {0}")]
    UnsupportedVersion(u8),
    #[error("reserved flag bits set")]
    ReservedFlags,
    #[error("station id must be 1-9 characters of A-Z, 0-9, '/', '-'")]
    InvalidStation,
    #[error("payload is {len} bytes; limit is {max}")]
    PayloadTooLarge { len: usize, max: usize },
    #[error("payload is not plaintext: {0}")]
    NotPlaintext(String),
    #[error("CRC mismatch (frame 0x{found:04X}, computed 0x{computed:04X})")]
    CrcMismatch { found: u16, computed: u16 },
    #[error("{0} trailing bytes after frame")]
    TrailingBytes(usize),
}

/// Validated station identifier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StationId(String);

impl StationId {
    pub fn parse(raw: &str) -> Result<Self, FrameError> {
        let valid = !raw.is_empty()
            && raw.len() <= MAX_STATION_LEN
            && raw
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'/' || b == b'-');
        if valid {
            Ok(Self(raw.to_string()))
        } else {
            Err(FrameError::InvalidStation)
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// A decoded (or to-be-encoded) Skybridge frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub station: StationId,
    pub sequence: u16,
    pub final_fragment: bool,
    pub payload: Vec<u8>,
}

impl Frame {
    /// Build a frame, validating the plaintext payload.
    pub fn new(station: StationId, sequence: u16, payload: &[u8]) -> Result<Self, FrameError> {
        validate_payload(payload)?;
        Ok(Self {
            station,
            sequence,
            final_fragment: true,
            payload: payload.to_vec(),
        })
    }

    pub fn text(&self) -> &str {
        std::str::from_utf8(&self.payload).unwrap_or_default()
    }

    pub fn encode(&self) -> Result<Vec<u8>, FrameError> {
        validate_payload(&self.payload)?;
        let station = self.station.as_str().as_bytes();
        let mut out =
            Vec::with_capacity(HEADER_FIXED + station.len() + self.payload.len() + CRC_LEN);
        out.extend_from_slice(&MAGIC);
        out.push(VERSION);
        out.push(if self.final_fragment { FLAG_FINAL } else { 0 });
        out.push(u8::try_from(station.len()).map_err(|_| FrameError::InvalidStation)?);
        out.extend_from_slice(station);
        out.extend_from_slice(&self.sequence.to_be_bytes());
        out.push(
            u8::try_from(self.payload.len()).map_err(|_| FrameError::PayloadTooLarge {
                len: self.payload.len(),
                max: MAX_PAYLOAD,
            })?,
        );
        out.extend_from_slice(&self.payload);
        let crc = crc16_x25(&out);
        out.extend_from_slice(&crc.to_be_bytes());
        Ok(out)
    }

    /// Decode exactly one frame; trailing bytes are an error.
    pub fn decode(bytes: &[u8]) -> Result<Self, FrameError> {
        let (frame, used) = Self::decode_prefix(bytes)?;
        if used != bytes.len() {
            return Err(FrameError::TrailingBytes(bytes.len() - used));
        }
        Ok(frame)
    }

    /// Total encoded length implied by a (possibly partial) header, if known.
    pub fn declared_len(bytes: &[u8]) -> Option<usize> {
        let station_len = usize::from(*bytes.get(4)?);
        let payload_len = usize::from(*bytes.get(7 + station_len)?);
        Some(HEADER_FIXED + station_len + payload_len + CRC_LEN)
    }

    /// Decode one frame from the start of `bytes`, returning bytes consumed.
    pub fn decode_prefix(bytes: &[u8]) -> Result<(Self, usize), FrameError> {
        if bytes.len() < HEADER_FIXED + 1 + CRC_LEN {
            return Err(FrameError::Truncated);
        }
        if bytes[0..2] != MAGIC {
            return Err(FrameError::BadMagic);
        }
        if bytes[2] != VERSION {
            return Err(FrameError::UnsupportedVersion(bytes[2]));
        }
        let flags = bytes[3];
        if flags & !FLAG_FINAL != 0 {
            return Err(FrameError::ReservedFlags);
        }
        let station_len = usize::from(bytes[4]);
        if station_len == 0 || station_len > MAX_STATION_LEN {
            return Err(FrameError::InvalidStation);
        }
        let total = Self::declared_len(bytes).ok_or(FrameError::Truncated)?;
        let payload_len = total - HEADER_FIXED - station_len - CRC_LEN;
        if payload_len > MAX_PAYLOAD {
            return Err(FrameError::PayloadTooLarge {
                len: payload_len,
                max: MAX_PAYLOAD,
            });
        }
        if bytes.len() < total {
            return Err(FrameError::Truncated);
        }
        let body_end = total - CRC_LEN;
        let found = u16::from_be_bytes([bytes[body_end], bytes[body_end + 1]]);
        let computed = crc16_x25(&bytes[..body_end]);
        if found != computed {
            return Err(FrameError::CrcMismatch { found, computed });
        }
        let station_raw = std::str::from_utf8(&bytes[5..5 + station_len])
            .map_err(|_| FrameError::InvalidStation)?;
        let station = StationId::parse(station_raw)?;
        let seq_at = 5 + station_len;
        let sequence = u16::from_be_bytes([bytes[seq_at], bytes[seq_at + 1]]);
        let payload = bytes[seq_at + 3..body_end].to_vec();
        validate_payload(&payload)?;
        Ok((
            Self {
                station,
                sequence,
                final_fragment: flags & FLAG_FINAL != 0,
                payload,
            },
            total,
        ))
    }
}

fn validate_payload(payload: &[u8]) -> Result<(), FrameError> {
    if payload.len() > MAX_PAYLOAD {
        return Err(FrameError::PayloadTooLarge {
            len: payload.len(),
            max: MAX_PAYLOAD,
        });
    }
    validate_plaintext(payload).map_err(FrameError::NotPlaintext)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn station() -> StationId {
        StationId::parse("N0CALL").unwrap()
    }

    #[test]
    fn crc16_x25_matches_reference_check_value() {
        assert_eq!(crc16_x25(b"123456789"), 0x906E);
        assert_eq!(crc16_x25(b""), 0x0000);
    }

    #[test]
    fn frame_round_trip() {
        let frame = Frame::new(station(), 42, b"resonance sample 7: 12.5 Hz").unwrap();
        let bytes = frame.encode().unwrap();
        assert_eq!(&bytes[0..2], b"SB");
        let decoded = Frame::decode(&bytes).unwrap();
        assert_eq!(decoded, frame);
        assert_eq!(decoded.text(), "resonance sample 7: 12.5 Hz");
    }

    #[test]
    fn empty_and_max_payloads_round_trip() {
        for payload in [Vec::new(), vec![b'a'; MAX_PAYLOAD]] {
            let frame = Frame::new(station(), 0, &payload).unwrap();
            let bytes = frame.encode().unwrap();
            assert!(bytes.len() <= MAX_FRAME_LEN);
            assert_eq!(Frame::decode(&bytes).unwrap(), frame);
        }
    }

    #[test]
    fn crc_detects_every_single_bit_flip() {
        let bytes = Frame::new(station(), 7, b"hello")
            .unwrap()
            .encode()
            .unwrap();
        for index in 0..bytes.len() {
            for bit in 0..8 {
                let mut corrupted = bytes.clone();
                corrupted[index] ^= 1 << bit;
                assert!(
                    Frame::decode(&corrupted).is_err(),
                    "flip at byte {index} bit {bit} went undetected"
                );
            }
        }
    }

    #[test]
    fn crc_mismatch_is_reported() {
        let mut bytes = Frame::new(station(), 1, b"payload")
            .unwrap()
            .encode()
            .unwrap();
        let last = bytes.len() - 1;
        bytes[last] ^= 0xFF;
        assert!(matches!(
            Frame::decode(&bytes),
            Err(FrameError::CrcMismatch { .. })
        ));
    }

    #[test]
    fn malformed_frames_are_rejected() {
        let good = Frame::new(station(), 1, b"x").unwrap().encode().unwrap();
        assert_eq!(Frame::decode(&good[..5]), Err(FrameError::Truncated));
        assert_eq!(
            Frame::decode(&good[..good.len() - 1]),
            Err(FrameError::Truncated)
        );

        let mut bad_magic = good.clone();
        bad_magic[0] = b'X';
        assert_eq!(Frame::decode(&bad_magic), Err(FrameError::BadMagic));

        let mut bad_version = good.clone();
        bad_version[2] = 9;
        assert_eq!(
            Frame::decode(&bad_version),
            Err(FrameError::UnsupportedVersion(9))
        );

        let mut reserved = good.clone();
        reserved[3] |= 0b1000_0000;
        assert_eq!(Frame::decode(&reserved), Err(FrameError::ReservedFlags));

        let mut trailing = good.clone();
        trailing.push(0);
        assert_eq!(Frame::decode(&trailing), Err(FrameError::TrailingBytes(1)));

        let mut zero_station = good;
        zero_station[4] = 0;
        assert_eq!(
            Frame::decode(&zero_station),
            Err(FrameError::InvalidStation)
        );
    }

    #[test]
    fn declared_oversized_payload_is_rejected() {
        let mut bytes = Frame::new(station(), 1, b"x").unwrap().encode().unwrap();
        let payload_len_at = 7 + station().as_str().len();
        bytes[payload_len_at] = 250;
        bytes.resize(8 + 6 + 250 + 2, b'a');
        assert!(matches!(
            Frame::decode(&bytes),
            Err(FrameError::PayloadTooLarge { len: 250, .. })
        ));
    }

    #[test]
    fn payload_limits_and_plaintext_rule() {
        assert!(matches!(
            Frame::new(station(), 0, &vec![b'a'; MAX_PAYLOAD + 1]),
            Err(FrameError::PayloadTooLarge { .. })
        ));
        assert!(matches!(
            Frame::new(station(), 0, &[0x00, 0x9f, 0xff]),
            Err(FrameError::NotPlaintext(_))
        ));
    }

    #[test]
    fn station_ids_are_restricted() {
        for ok in ["N0CALL", "VE3/W1AW", "RIG-1", "A"] {
            StationId::parse(ok).unwrap();
        }
        for bad in ["", "n0call", "TOOLONGID1", "N0 CALL", "N0CALL!"] {
            assert!(StationId::parse(bad).is_err(), "{bad:?}");
        }
    }
}
