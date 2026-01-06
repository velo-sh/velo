//! H-29 Alignment Enforcement
//!
//! This module implements the critical padding algorithm required to ensure
//! 64-byte alignment for tensor data in shared memory.

use thiserror::Error;

#[derive(Error, Debug)]
pub enum AlignmentError {
    #[error("Header length causes integer overflow")]
    HeaderTooLarge,
}

/// Calculates the required padding to ensure the next byte is 64-byte aligned.
///
/// H-29 Invariant: `(sizeof(u64) + header_len + padding) % 64 == 0`
/// Note that the initial `sizeof(u64)` comes from the length prefix in safetensors
/// format, but typically the "header length" we get is just the JSON bytes.
///
/// The standard safetensors layout is:
/// [u64: length_of_header] [header_bytes] [padding] [tensor_data]
///
/// The goal is for `tensor_data` to start at % 64 == 0.
#[inline]
pub fn calculate_padding(header_len: usize) -> Result<usize, AlignmentError> {
    let prefix_size = std::mem::size_of::<u64>();
    // SAFETY: Checked add to prevent overflow attacks (Council Review P0)
    let current_offset = prefix_size
        .checked_add(header_len)
        .ok_or(AlignmentError::HeaderTooLarge)?;

    let remainder = current_offset % 64;

    if remainder == 0 {
        Ok(0)
    } else {
        Ok(64 - remainder)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_padding_calculations() {
        // H-29 Test Cases

        // Case 1: Perfect alignment
        assert_eq!(calculate_padding(56).unwrap(), 0);

        // Case 2: Remainder 9 -> Padding 55
        assert_eq!(calculate_padding(1).unwrap(), 55);

        // Case 3: Remainder 44 -> Padding 20
        assert_eq!(calculate_padding(100).unwrap(), 20);

        // Case 4: Overflow
        assert!(calculate_padding(usize::MAX).is_err());
    }
}
