//! Skybridge software baseband modem: continuous-phase binary FSK.
//!
//! Produces and consumes mono `f32` audio samples in memory. It is a pure
//! signal-processing component with no device access: nothing here opens a
//! sound card, keys a transmitter, selects a frequency, or controls power.
//!
//! Line format: 32-bit `1010…` preamble, a 16-bit sync word, the frame,
//! then an 8-bit zero tail. The sync word selects the coding:
//!
//! - `0x2DD4`: plain — frame bytes MSB-first;
//! - `0xD22B`: Hamming(7,4) with block interleaving ([`fec`](super::fec)).
//!
//! The demodulator accepts both. Default parameters are 100 baud with
//! 1500/1700 Hz tones at 8 kHz, which keeps the tones orthogonal over one
//! symbol and fits a narrow audio passband; FEC is on by default.

use super::fec;
use super::frame::{Frame, FrameError, MAX_FRAME_LEN};

const PREAMBLE_BITS: usize = 32;
const SYNC_PLAIN: u16 = 0x2DD4;
const SYNC_FEC: u16 = 0xD22B;
const TAIL_BITS: usize = 8;
const AMPLITUDE: f32 = 0.5;
/// Upper bound on samples accepted by the demodulator (~5 minutes at 8 kHz).
pub const MAX_DEMOD_SAMPLES: usize = 8_000 * 300;

/// Line coding of a transmitted frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Coding {
    /// Frame bytes as-is (CRC detects errors; nothing is corrected).
    Plain,
    /// Hamming(7,4), interleaved: corrects one bit per codeword and bursts
    /// up to eight bits per block, at 1.75× airtime.
    Hamming74,
}

impl Coding {
    pub fn label(self) -> &'static str {
        match self {
            Self::Plain => "none",
            Self::Hamming74 => "Hamming(7,4), interleaved",
        }
    }
}

/// Modem parameters.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ModemConfig {
    pub sample_rate: u32,
    pub baud: u32,
    /// Tone for a `1` bit.
    pub mark_hz: f32,
    /// Tone for a `0` bit.
    pub space_hz: f32,
    /// Coding used when modulating. Demodulation accepts either.
    pub coding: Coding,
}

impl Default for ModemConfig {
    fn default() -> Self {
        Self {
            sample_rate: 8_000,
            baud: 100,
            mark_hz: 1_700.0,
            space_hz: 1_500.0,
            coding: Coding::Hamming74,
        }
    }
}

/// Modem failure.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum ModemError {
    #[error("invalid modem configuration: {0}")]
    InvalidConfig(&'static str),
    #[error("input has {0} samples; limit is {MAX_DEMOD_SAMPLES}")]
    TooManySamples(usize),
    #[error("no Skybridge frame found in the signal")]
    NoFrame,
    #[error("frame found but rejected: {0}")]
    Frame(#[from] FrameError),
}

impl ModemConfig {
    pub fn validate(&self) -> Result<(), ModemError> {
        if self.baud == 0 || self.sample_rate == 0 {
            return Err(ModemError::InvalidConfig(
                "sample rate and baud must be non-zero",
            ));
        }
        if !self.sample_rate.is_multiple_of(self.baud) {
            return Err(ModemError::InvalidConfig(
                "sample rate must be a multiple of baud",
            ));
        }
        if self.samples_per_symbol() < 8 {
            return Err(ModemError::InvalidConfig(
                "need at least 8 samples per symbol",
            ));
        }
        let nyquist = self.sample_rate as f32 / 2.0;
        for tone in [self.mark_hz, self.space_hz] {
            if !(tone > 0.0 && tone < nyquist * 0.9) {
                return Err(ModemError::InvalidConfig(
                    "tones must be below 90% of Nyquist",
                ));
            }
        }
        if (self.mark_hz - self.space_hz).abs() < self.baud as f32 {
            return Err(ModemError::InvalidConfig(
                "tone spacing must be at least the baud rate",
            ));
        }
        Ok(())
    }

    pub fn samples_per_symbol(&self) -> usize {
        (self.sample_rate / self.baud.max(1)) as usize
    }

    /// Signal duration in seconds for an encoded frame of `frame_len` bytes.
    pub fn airtime_secs(&self, frame_len: usize) -> f32 {
        let coded = match self.coding {
            Coding::Plain => frame_len * 8,
            Coding::Hamming74 => frame_len.div_ceil(fec::BLOCK_BYTES).max(1) * fec::BLOCK_BITS,
        };
        let bits = PREAMBLE_BITS + 16 + coded + TAIL_BITS;
        bits as f32 / self.baud as f32
    }
}

fn line_bits(frame_bytes: &[u8], coding: Coding) -> Vec<bool> {
    let sync = match coding {
        Coding::Plain => SYNC_PLAIN,
        Coding::Hamming74 => SYNC_FEC,
    };
    let mut bits = Vec::with_capacity(PREAMBLE_BITS + 16 + frame_bytes.len() * 14 + TAIL_BITS);
    bits.extend((0..PREAMBLE_BITS).map(|i| i % 2 == 0));
    bits.extend((0..16).rev().map(|i| (sync >> i) & 1 == 1));
    match coding {
        Coding::Plain => {
            for byte in frame_bytes {
                bits.extend((0..8).rev().map(|i| (byte >> i) & 1 == 1));
            }
        }
        Coding::Hamming74 => bits.extend(fec::encode(frame_bytes)),
    }
    bits.extend(std::iter::repeat_n(false, TAIL_BITS));
    bits
}

/// Modulate an encoded frame into baseband samples using `config.coding`.
pub fn modulate(config: &ModemConfig, frame_bytes: &[u8]) -> Result<Vec<f32>, ModemError> {
    config.validate()?;
    Ok(modulate_bits(
        config,
        &line_bits(frame_bytes, config.coding),
    ))
}

/// Continuous-phase FSK for a line bit sequence (config already validated).
fn modulate_bits(config: &ModemConfig, bits: &[bool]) -> Vec<f32> {
    let sps = config.samples_per_symbol();
    let rate = config.sample_rate as f32;
    let mut phase = 0.0_f32;
    let mut samples = Vec::with_capacity(bits.len() * sps);
    for &bit in bits {
        let step =
            std::f32::consts::TAU * if bit { config.mark_hz } else { config.space_hz } / rate;
        for _ in 0..sps {
            samples.push(AMPLITUDE * phase.sin());
            phase = (phase + step) % std::f32::consts::TAU;
        }
    }
    samples
}

/// Goertzel power of `freq` over `window`.
fn goertzel_power(window: &[f32], sample_rate: f32, freq: f32) -> f32 {
    let coeff = 2.0 * (std::f32::consts::TAU * freq / sample_rate).cos();
    let (mut s1, mut s2) = (0.0_f32, 0.0_f32);
    for &x in window {
        let s0 = x + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    s1 * s1 + s2 * s2 - coeff * s1 * s2
}

fn slice_bits(config: &ModemConfig, samples: &[f32], offset: usize) -> Vec<bool> {
    let sps = config.samples_per_symbol();
    let rate = config.sample_rate as f32;
    samples[offset.min(samples.len())..]
        .chunks_exact(sps)
        .map(|window| {
            goertzel_power(window, rate, config.mark_hz)
                > goertzel_power(window, rate, config.space_hz)
        })
        .collect()
}

fn bits_to_byte(bits: &[bool]) -> u8 {
    bits.iter()
        .fold(0u8, |acc, bit| (acc << 1) | u8::from(*bit))
}

/// A frame recovered from a signal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Demodulated {
    pub frame: Frame,
    pub coding: Coding,
    /// Bits repaired by FEC (always 0 for plain frames).
    pub corrected_bits: usize,
    /// Sample index where the frame's first bit starts.
    pub sample_offset: usize,
}

/// Try to read one frame whose first bit is at `start`. Returns the frame,
/// the corrected bit count, and the index just past its last line bit.
fn read_frame(
    bits: &[bool],
    start: usize,
    coding: Coding,
) -> Result<(Frame, usize, usize), FrameError> {
    let mut bytes = Vec::with_capacity(MAX_FRAME_LEN + fec::BLOCK_BYTES);
    let mut cursor = start;
    let mut corrected = 0;
    while bytes.len() < MAX_FRAME_LEN {
        if let Some(total) = Frame::declared_len(&bytes) {
            if bytes.len() >= total {
                break;
            }
        }
        match coding {
            Coding::Plain => {
                let byte = bits
                    .get(cursor..cursor + 8)
                    .map(bits_to_byte)
                    .ok_or(FrameError::Truncated)?;
                bytes.push(byte);
                cursor += 8;
            }
            Coding::Hamming74 => {
                let (block, fixed) = bits
                    .get(cursor..cursor + fec::BLOCK_BITS)
                    .and_then(fec::decode_block)
                    .ok_or(FrameError::Truncated)?;
                bytes.extend_from_slice(&block);
                corrected += fixed;
                cursor += fec::BLOCK_BITS;
            }
        }
    }
    let (frame, used) = Frame::decode_prefix(&bytes)?;
    let end = match coding {
        Coding::Plain => start + used * 8,
        Coding::Hamming74 => cursor,
    };
    Ok((frame, corrected, end))
}

/// Demodulate every valid frame in a signal, in signal order.
///
/// Searches symbol timing offsets and sync-word positions; a candidate is
/// accepted only if the frame decodes and its CRC matches. The same frame
/// found at several timing offsets is reported once (fewest corrections).
pub fn demodulate_all(
    config: &ModemConfig,
    samples: &[f32],
) -> Result<Vec<Demodulated>, ModemError> {
    config.validate()?;
    if samples.len() > MAX_DEMOD_SAMPLES {
        return Err(ModemError::TooManySamples(samples.len()));
    }
    let sps = config.samples_per_symbol();
    let step = (sps / 8).max(1);
    let mut found: Vec<Demodulated> = Vec::new();
    let mut last_error = None;
    for offset in (0..sps).step_by(step) {
        let bits = slice_bits(config, samples, offset);
        let mut shift: u16 = 0;
        let mut index = 0;
        while index < bits.len() {
            shift = (shift << 1) | u16::from(bits[index]);
            let coding = match shift {
                SYNC_PLAIN if index >= 15 => Some(Coding::Plain),
                SYNC_FEC if index >= 15 => Some(Coding::Hamming74),
                _ => None,
            };
            index += 1;
            let Some(coding) = coding else {
                continue;
            };
            match read_frame(&bits, index, coding) {
                Ok((frame, corrected_bits, end)) => {
                    found.push(Demodulated {
                        frame,
                        coding,
                        corrected_bits,
                        sample_offset: offset + index * sps,
                    });
                    index = end;
                    shift = 0;
                }
                Err(error) => last_error = Some(error),
            }
        }
    }
    found.sort_by_key(|d| (d.sample_offset, d.corrected_bits));
    // Frames start at least a preamble apart; nearer candidates are the same
    // frame seen at another timing offset.
    let min_gap = sps * PREAMBLE_BITS;
    let mut frames: Vec<Demodulated> = Vec::with_capacity(found.len());
    for candidate in found {
        match frames.last_mut() {
            Some(last) if candidate.sample_offset < last.sample_offset + min_gap => {
                if candidate.corrected_bits < last.corrected_bits {
                    *last = candidate;
                }
            }
            _ => frames.push(candidate),
        }
    }
    if frames.is_empty() {
        return Err(last_error.map_or(ModemError::NoFrame, ModemError::Frame));
    }
    Ok(frames)
}

/// Demodulate and return the first valid frame.
pub fn demodulate(config: &ModemConfig, samples: &[f32]) -> Result<Frame, ModemError> {
    demodulate_all(config, samples).map(|mut frames| frames.swap_remove(0).frame)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rig::skybridge::frame::StationId;

    fn frame(text: &str) -> Frame {
        Frame::new(StationId::parse("N0CALL").unwrap(), 3, text.as_bytes()).unwrap()
    }

    /// Deterministic noise (xorshift), amplitude in [-amp, amp].
    fn noise(len: usize, amp: f32, mut state: u32) -> Vec<f32> {
        (0..len)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 17;
                state ^= state << 5;
                (state as f32 / u32::MAX as f32 * 2.0 - 1.0) * amp
            })
            .collect()
    }

    /// Modulate several frames back to back, as the transport does.
    fn signal(config: &ModemConfig, frames: &[Frame]) -> Vec<f32> {
        frames
            .iter()
            .flat_map(|f| modulate(config, &f.encode().unwrap()).unwrap())
            .collect()
    }

    fn plain() -> ModemConfig {
        ModemConfig {
            coding: Coding::Plain,
            ..ModemConfig::default()
        }
    }

    #[test]
    fn sync_words_never_match_inside_the_preamble() {
        for (coding, sync) in [(Coding::Plain, SYNC_PLAIN), (Coding::Hamming74, SYNC_FEC)] {
            let bits = line_bits(&[], coding);
            let mut shift: u16 = 0;
            for (index, bit) in bits.iter().take(PREAMBLE_BITS + 16).enumerate() {
                shift = (shift << 1) | u16::from(*bit);
                if index >= 15 && index + 1 < PREAMBLE_BITS + 16 {
                    assert!(
                        shift != SYNC_PLAIN && shift != SYNC_FEC,
                        "{coding:?} at {index}"
                    );
                }
            }
            assert_eq!(shift, sync);
        }
    }

    #[test]
    fn fec_corrects_errors_that_break_plain_frames() {
        let original = frame("burst errors are corrected by the interleaver");
        let bytes = original.encode().unwrap();
        for (config, expect_ok) in [(ModemConfig::default(), true), (plain(), false)] {
            let mut bits = line_bits(&bytes, config.coding);
            // A burst of 6 flipped bits inside the frame body.
            for bit in &mut bits[PREAMBLE_BITS + 16 + 100..PREAMBLE_BITS + 16 + 106] {
                *bit ^= true;
            }
            let samples = modulate_bits(&config, &bits);
            let result = demodulate_all(&config, &samples);
            if expect_ok {
                let frames = result.unwrap();
                assert_eq!(frames[0].frame, original);
                assert_eq!(frames[0].corrected_bits, 6);
                assert_eq!(frames[0].coding, Coding::Hamming74);
            } else {
                assert!(result.is_err());
            }
        }
    }

    #[test]
    fn demodulate_all_finds_every_frame_once_in_order() {
        let frames: Vec<Frame> = ["one", "two", "three"].iter().map(|t| frame(t)).collect();
        for config in [ModemConfig::default(), plain()] {
            let mut samples = vec![0.0; 777];
            samples.extend(signal(&config, &frames));
            let noisy: Vec<f32> = samples
                .iter()
                .zip(noise(samples.len(), 0.2, 0xBEEF))
                .map(|(s, n)| s + n)
                .collect();
            let decoded: Vec<Frame> = demodulate_all(&config, &noisy)
                .unwrap()
                .into_iter()
                .map(|d| d.frame)
                .collect();
            assert_eq!(decoded, frames, "{:?}", config.coding);
        }
    }

    #[test]
    fn fec_airtime_is_longer_than_plain() {
        let fec = ModemConfig::default().airtime_secs(MAX_FRAME_LEN);
        let plain = plain().airtime_secs(MAX_FRAME_LEN);
        assert!(fec > plain * 1.7 && fec < plain * 1.8, "{fec} vs {plain}");
    }

    #[test]
    fn default_config_is_valid_and_orthogonal() {
        let config = ModemConfig::default();
        config.validate().unwrap();
        assert_eq!(config.samples_per_symbol(), 80);
    }

    #[test]
    fn invalid_configs_are_rejected() {
        let bad = [
            ModemConfig {
                baud: 0,
                ..ModemConfig::default()
            },
            ModemConfig {
                baud: 300,
                ..ModemConfig::default()
            },
            ModemConfig {
                mark_hz: 4_000.0,
                ..ModemConfig::default()
            },
            ModemConfig {
                mark_hz: 1_550.0,
                ..ModemConfig::default()
            },
            ModemConfig {
                sample_rate: 400,
                baud: 100,
                ..ModemConfig::default()
            },
        ];
        for config in bad {
            assert!(config.validate().is_err(), "{config:?}");
        }
    }

    #[test]
    fn baseband_round_trip() {
        let config = ModemConfig::default();
        let original = frame("field note: coherence holds at node 3");
        let samples = modulate(&config, &original.encode().unwrap()).unwrap();
        assert!(samples.iter().all(|s| s.abs() <= AMPLITUDE + f32::EPSILON));
        assert_eq!(demodulate(&config, &samples).unwrap(), original);
    }

    #[test]
    fn round_trip_with_leading_silence_and_noise() {
        let config = ModemConfig::default();
        let original = frame("PING");
        let mut samples = vec![0.0; 1_234];
        samples.extend(modulate(&config, &original.encode().unwrap()).unwrap());
        samples.extend(vec![0.0; 500]);
        let noisy: Vec<f32> = samples
            .iter()
            .zip(noise(samples.len(), 0.25, 0x5EED))
            .map(|(s, n)| s + n)
            .collect();
        assert_eq!(demodulate(&config, &noisy).unwrap(), original);
    }

    #[test]
    fn max_payload_round_trip() {
        let config = ModemConfig::default();
        let original = frame(&"r".repeat(crate::rig::skybridge::frame::MAX_PAYLOAD));
        let samples = modulate(&config, &original.encode().unwrap()).unwrap();
        assert_eq!(demodulate(&config, &samples).unwrap(), original);
    }

    #[test]
    fn corrupted_bits_fail_crc_instead_of_decoding() {
        let config = ModemConfig::default();
        let mut bytes = frame("integrity matters").encode().unwrap();
        // Flip one payload bit after the CRC was computed ("e" -> "d").
        bytes[16] ^= 0x01;
        let samples = modulate(&config, &bytes).unwrap();
        assert!(matches!(
            demodulate(&config, &samples),
            Err(ModemError::Frame(FrameError::CrcMismatch { .. }))
        ));
    }

    #[test]
    fn silence_and_noise_contain_no_frame() {
        let config = ModemConfig::default();
        assert_eq!(
            demodulate(&config, &vec![0.0; 16_000]),
            Err(ModemError::NoFrame)
        );
        assert!(demodulate(&config, &noise(16_000, 0.5, 7)).is_err());
    }

    #[test]
    fn oversized_input_is_refused() {
        let config = ModemConfig::default();
        let samples = vec![0.0; MAX_DEMOD_SAMPLES + 1];
        assert!(matches!(
            demodulate(&config, &samples),
            Err(ModemError::TooManySamples(_))
        ));
    }
}
