//! Skybridge software baseband modem: continuous-phase binary FSK.
//!
//! Produces and consumes mono `f32` audio samples in memory. It is a pure
//! signal-processing component with no device access: nothing here opens a
//! sound card, keys a transmitter, selects a frequency, or controls power.
//!
//! Line format: 32-bit `1010…` preamble, 16-bit sync word `0x2DD4`, the
//! frame bytes MSB-first, then an 8-bit zero tail. Default parameters are
//! 100 baud with 1500/1700 Hz tones at 8 kHz, which keeps the tones
//! orthogonal over one symbol and fits a narrow audio passband.

use super::frame::{Frame, FrameError, MAX_FRAME_LEN};

const PREAMBLE_BITS: usize = 32;
const SYNC_WORD: u16 = 0x2DD4;
const TAIL_BITS: usize = 8;
const AMPLITUDE: f32 = 0.5;
/// Upper bound on samples accepted by the demodulator (~5 minutes at 8 kHz).
pub const MAX_DEMOD_SAMPLES: usize = 8_000 * 300;

/// Modem parameters.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ModemConfig {
    pub sample_rate: u32,
    pub baud: u32,
    /// Tone for a `1` bit.
    pub mark_hz: f32,
    /// Tone for a `0` bit.
    pub space_hz: f32,
}

impl Default for ModemConfig {
    fn default() -> Self {
        Self {
            sample_rate: 8_000,
            baud: 100,
            mark_hz: 1_700.0,
            space_hz: 1_500.0,
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
        let bits = PREAMBLE_BITS + 16 + frame_len * 8 + TAIL_BITS;
        bits as f32 / self.baud as f32
    }
}

fn line_bits(frame_bytes: &[u8]) -> Vec<bool> {
    let mut bits = Vec::with_capacity(PREAMBLE_BITS + 16 + frame_bytes.len() * 8 + TAIL_BITS);
    bits.extend((0..PREAMBLE_BITS).map(|i| i % 2 == 0));
    bits.extend((0..16).rev().map(|i| (SYNC_WORD >> i) & 1 == 1));
    for byte in frame_bytes {
        bits.extend((0..8).rev().map(|i| (byte >> i) & 1 == 1));
    }
    bits.extend(std::iter::repeat_n(false, TAIL_BITS));
    bits
}

/// Modulate an encoded frame into baseband samples.
pub fn modulate(config: &ModemConfig, frame_bytes: &[u8]) -> Result<Vec<f32>, ModemError> {
    config.validate()?;
    let sps = config.samples_per_symbol();
    let rate = config.sample_rate as f32;
    let mut phase = 0.0_f32;
    let bits = line_bits(frame_bytes);
    let mut samples = Vec::with_capacity(bits.len() * sps);
    for bit in bits {
        let step =
            std::f32::consts::TAU * if bit { config.mark_hz } else { config.space_hz } / rate;
        for _ in 0..sps {
            samples.push(AMPLITUDE * phase.sin());
            phase = (phase + step) % std::f32::consts::TAU;
        }
    }
    Ok(samples)
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

/// Try to read one frame starting right after a sync word at `start`.
fn read_frame(bits: &[bool], start: usize) -> Result<Frame, FrameError> {
    let byte_at = |index: usize| -> Option<u8> {
        let from = start + index * 8;
        bits.get(from..from + 8).map(bits_to_byte)
    };
    let mut bytes = Vec::with_capacity(MAX_FRAME_LEN);
    while bytes.len() < MAX_FRAME_LEN {
        if let Some(total) = Frame::declared_len(&bytes) {
            if bytes.len() >= total {
                break;
            }
        }
        match byte_at(bytes.len()) {
            Some(byte) => bytes.push(byte),
            None => return Err(FrameError::Truncated),
        }
    }
    let (frame, _) = Frame::decode_prefix(&bytes)?;
    Ok(frame)
}

/// Demodulate baseband samples and return the first valid frame.
///
/// Searches symbol timing offsets and sync-word positions; a candidate is
/// accepted only if the frame decodes and its CRC matches.
pub fn demodulate(config: &ModemConfig, samples: &[f32]) -> Result<Frame, ModemError> {
    config.validate()?;
    if samples.len() > MAX_DEMOD_SAMPLES {
        return Err(ModemError::TooManySamples(samples.len()));
    }
    let sps = config.samples_per_symbol();
    let step = (sps / 8).max(1);
    let mut last_error = None;
    for offset in (0..sps).step_by(step) {
        let bits = slice_bits(config, samples, offset);
        let mut shift: u16 = 0;
        for (index, bit) in bits.iter().enumerate() {
            shift = (shift << 1) | u16::from(*bit);
            if index >= 15 && shift == SYNC_WORD {
                match read_frame(&bits, index + 1) {
                    Ok(frame) => return Ok(frame),
                    Err(error) => last_error = Some(error),
                }
            }
        }
    }
    Err(last_error.map_or(ModemError::NoFrame, ModemError::Frame))
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
