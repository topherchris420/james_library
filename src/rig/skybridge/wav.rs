//! Minimal PCM16 mono WAV I/O for Skybridge baseband files.
//!
//! Only the format the modem produces is accepted: RIFF/WAVE, PCM
//! (format 1), one channel, 16-bit samples. Anything else is rejected
//! explicitly rather than guessed at.

use anyhow::{Context, Result, bail};
use std::path::Path;

/// Largest WAV file read (bytes).
pub const MAX_WAV_BYTES: u64 = 64 * 1024 * 1024;

/// Encode samples (clamped to [-1, 1]) as a PCM16 mono WAV file image.
pub fn encode_pcm16(samples: &[f32], sample_rate: u32) -> Vec<u8> {
    let data_len = u32::try_from(samples.len() * 2).unwrap_or(u32::MAX);
    let mut out = Vec::with_capacity(44 + samples.len() * 2);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&(36 + data_len).to_le_bytes());
    out.extend_from_slice(b"WAVEfmt ");
    out.extend_from_slice(&16u32.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes()); // PCM
    out.extend_from_slice(&1u16.to_le_bytes()); // mono
    out.extend_from_slice(&sample_rate.to_le_bytes());
    out.extend_from_slice(&(sample_rate * 2).to_le_bytes()); // byte rate
    out.extend_from_slice(&2u16.to_le_bytes()); // block align
    out.extend_from_slice(&16u16.to_le_bytes()); // bits per sample
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        let scaled = (sample.clamp(-1.0, 1.0) * f32::from(i16::MAX)).round();
        #[allow(clippy::cast_possible_truncation)]
        out.extend_from_slice(&(scaled as i16).to_le_bytes());
    }
    out
}

/// Decode a PCM16 mono WAV image into samples and its sample rate.
pub fn decode_pcm16(bytes: &[u8]) -> Result<(Vec<f32>, u32)> {
    if bytes.len() < 12 || &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        bail!("not a RIFF/WAVE file");
    }
    let mut cursor = 12;
    let mut format: Option<(u16, u16, u32, u16)> = None;
    while cursor + 8 <= bytes.len() {
        let id = &bytes[cursor..cursor + 4];
        let size = u32::from_le_bytes(bytes[cursor + 4..cursor + 8].try_into()?) as usize;
        let body_start = cursor + 8;
        let body_end = body_start
            .checked_add(size)
            .filter(|end| *end <= bytes.len())
            .context("WAV chunk extends past end of file")?;
        let body = &bytes[body_start..body_end];
        match id {
            b"fmt " => {
                if body.len() < 16 {
                    bail!("WAV fmt chunk is too short");
                }
                format = Some((
                    u16::from_le_bytes([body[0], body[1]]),
                    u16::from_le_bytes([body[2], body[3]]),
                    u32::from_le_bytes([body[4], body[5], body[6], body[7]]),
                    u16::from_le_bytes([body[14], body[15]]),
                ));
            }
            b"data" => {
                let Some((audio_format, channels, sample_rate, bits)) = format else {
                    bail!("WAV data chunk precedes fmt chunk");
                };
                if audio_format != 1 || channels != 1 || bits != 16 {
                    bail!(
                        "unsupported WAV format (need PCM mono 16-bit; got format {audio_format}, {channels} channel(s), {bits}-bit)"
                    );
                }
                let samples = body
                    .chunks_exact(2)
                    .map(|pair| {
                        f32::from(i16::from_le_bytes([pair[0], pair[1]])) / f32::from(i16::MAX)
                    })
                    .collect();
                return Ok((samples, sample_rate));
            }
            _ => {}
        }
        // Chunks are word-aligned.
        cursor = body_end + (size % 2);
    }
    bail!("WAV file has no data chunk")
}

/// Write a WAV file.
pub fn write_file(path: &Path, samples: &[f32], sample_rate: u32) -> Result<()> {
    std::fs::write(path, encode_pcm16(samples, sample_rate))
        .with_context(|| format!("writing {}", path.display()))
}

/// Read a WAV file, refusing files over [`MAX_WAV_BYTES`].
pub fn read_file(path: &Path) -> Result<(Vec<f32>, u32)> {
    let size = std::fs::metadata(path)
        .with_context(|| format!("reading {}", path.display()))?
        .len();
    if size > MAX_WAV_BYTES {
        bail!(
            "{} is {size} bytes; limit is {MAX_WAV_BYTES}",
            path.display()
        );
    }
    let bytes = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    decode_pcm16(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pcm16_round_trip_within_quantization() {
        let samples = vec![0.0, 0.5, -0.5, 1.0, -1.0, 0.25];
        let bytes = encode_pcm16(&samples, 8_000);
        assert_eq!(bytes.len(), 44 + samples.len() * 2);
        let (decoded, rate) = decode_pcm16(&bytes).unwrap();
        assert_eq!(rate, 8_000);
        for (a, b) in samples.iter().zip(decoded.iter()) {
            assert!((a - b).abs() < 1e-4, "{a} vs {b}");
        }
    }

    #[test]
    fn unsupported_or_malformed_wav_is_rejected() {
        assert!(decode_pcm16(b"not a wav").is_err());
        let mut stereo = encode_pcm16(&[0.0; 4], 8_000);
        stereo[22] = 2; // channels
        assert!(decode_pcm16(&stereo).is_err());
        let mut truncated = encode_pcm16(&[0.0; 4], 8_000);
        truncated.truncate(46);
        assert!(decode_pcm16(&truncated).is_err());
    }

    #[test]
    fn files_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("frame.wav");
        write_file(&path, &[0.1, -0.1], 8_000).unwrap();
        let (samples, rate) = read_file(&path).unwrap();
        assert_eq!(rate, 8_000);
        assert_eq!(samples.len(), 2);
    }
}
