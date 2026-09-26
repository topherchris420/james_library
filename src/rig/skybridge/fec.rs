//! Forward error correction for Skybridge: Hamming(7,4) with block
//! interleaving.
//!
//! Each byte becomes two 7-bit Hamming codewords (high nibble first), which
//! corrects any single bit error per codeword. Codewords are grouped in
//! blocks of [`BLOCK_CODEWORDS`] and interleaved column-wise, so a burst of
//! up to [`BLOCK_CODEWORDS`] consecutive bit errors touches each codeword at
//! most once and is fully corrected. Frames are zero-padded to whole blocks;
//! the frame header's length field tells the decoder where the frame ends.
//!
//! FEC corrects channel errors; the frame CRC still decides acceptance.

/// Bytes per interleaved block.
pub const BLOCK_BYTES: usize = 4;
/// Codewords per block (two per byte).
pub const BLOCK_CODEWORDS: usize = BLOCK_BYTES * 2;
/// Line bits per block.
pub const BLOCK_BITS: usize = BLOCK_CODEWORDS * 7;

/// Encode a nibble as a Hamming(7,4) codeword, positions 1..=7 =
/// p1 p2 d1 p3 d2 d3 d4 (index 0 is position 1).
fn encode_nibble(nibble: u8) -> [bool; 7] {
    let d = |i: u8| (nibble >> (3 - i)) & 1 == 1;
    let (d1, d2, d3, d4) = (d(0), d(1), d(2), d(3));
    [d1 ^ d2 ^ d4, d1 ^ d3 ^ d4, d1, d2 ^ d3 ^ d4, d2, d3, d4]
}

/// Decode a codeword, correcting at most one bit. Returns the nibble and
/// whether a bit was corrected.
fn decode_codeword(mut word: [bool; 7]) -> (u8, bool) {
    let bit = |i: usize| u8::from(word[i - 1]);
    let syndrome = (bit(1) ^ bit(3) ^ bit(5) ^ bit(7))
        | ((bit(2) ^ bit(3) ^ bit(6) ^ bit(7)) << 1)
        | ((bit(4) ^ bit(5) ^ bit(6) ^ bit(7)) << 2);
    if syndrome != 0 {
        word[usize::from(syndrome) - 1] ^= true;
    }
    let nibble = (u8::from(word[2]) << 3)
        | (u8::from(word[4]) << 2)
        | (u8::from(word[5]) << 1)
        | u8::from(word[6]);
    (nibble, syndrome != 0)
}

/// Encode bytes (zero-padded to whole blocks) into interleaved line bits.
pub fn encode(bytes: &[u8]) -> Vec<bool> {
    let blocks = bytes.len().div_ceil(BLOCK_BYTES).max(1);
    let mut out = Vec::with_capacity(blocks * BLOCK_BITS);
    for block in 0..blocks {
        let mut codewords = [[false; 7]; BLOCK_CODEWORDS];
        for (index, codeword) in codewords.iter_mut().enumerate() {
            let byte = bytes
                .get(block * BLOCK_BYTES + index / 2)
                .copied()
                .unwrap_or(0);
            let nibble = if index % 2 == 0 {
                byte >> 4
            } else {
                byte & 0x0F
            };
            *codeword = encode_nibble(nibble);
        }
        for position in 0..7 {
            out.extend(codewords.iter().map(|codeword| codeword[position]));
        }
    }
    out
}

/// Decode one interleaved block. Returns the bytes and the number of
/// corrected bits.
pub fn decode_block(bits: &[bool]) -> Option<([u8; BLOCK_BYTES], usize)> {
    if bits.len() < BLOCK_BITS {
        return None;
    }
    let mut bytes = [0u8; BLOCK_BYTES];
    let mut corrected = 0;
    for index in 0..BLOCK_CODEWORDS {
        let mut codeword = [false; 7];
        for (position, bit) in codeword.iter_mut().enumerate() {
            *bit = bits[position * BLOCK_CODEWORDS + index];
        }
        let (nibble, fixed) = decode_codeword(codeword);
        corrected += usize::from(fixed);
        bytes[index / 2] |= if index % 2 == 0 { nibble << 4 } else { nibble };
    }
    Some((bytes, corrected))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decode_all(bits: &[bool]) -> (Vec<u8>, usize) {
        let mut bytes = Vec::new();
        let mut corrected = 0;
        for block in bits.chunks(BLOCK_BITS) {
            let (decoded, fixed) = decode_block(block).unwrap();
            bytes.extend_from_slice(&decoded);
            corrected += fixed;
        }
        (bytes, corrected)
    }

    #[test]
    fn every_nibble_survives_every_single_bit_error() {
        for nibble in 0..16u8 {
            let word = encode_nibble(nibble);
            assert_eq!(decode_codeword(word), (nibble, false));
            for flip in 0..7 {
                let mut damaged = word;
                damaged[flip] ^= true;
                assert_eq!(
                    decode_codeword(damaged),
                    (nibble, true),
                    "{nibble} bit {flip}"
                );
            }
        }
    }

    #[test]
    fn round_trip_pads_to_whole_blocks() {
        let data = b"SB field note";
        let bits = encode(data);
        assert_eq!(bits.len() % BLOCK_BITS, 0);
        let (bytes, corrected) = decode_all(&bits);
        assert_eq!(&bytes[..data.len()], data);
        assert!(bytes[data.len()..].iter().all(|b| *b == 0));
        assert_eq!(corrected, 0);
    }

    #[test]
    fn corrects_any_burst_up_to_block_depth() {
        let data: Vec<u8> = (0..=255u8).collect();
        let clean = encode(&data);
        for start in 0..clean.len() - BLOCK_CODEWORDS {
            let mut bits = clean.clone();
            for bit in &mut bits[start..start + BLOCK_CODEWORDS] {
                *bit ^= true;
            }
            let (bytes, corrected) = decode_all(&bits);
            assert_eq!(&bytes[..data.len()], &data[..], "burst at {start}");
            assert_eq!(corrected, BLOCK_CODEWORDS);
        }
    }
}
