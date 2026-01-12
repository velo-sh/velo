//! H-29 Alignment Enforcement
//!
//! This module implements the critical padding algorithm required to ensure
//! 64-byte alignment for tensor data in shared memory.

use crate::shm::constants::{HEADER_LEN_SIZE, VELO_ALIGNMENT};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum AlignmentError {
    #[error("Header length causes integer overflow")]
    HeaderTooLarge,
}

/// Calculates the required padding to ensure the next byte is 64-byte aligned.
///
/// H-29 Invariant: `(HEADER_LEN_SIZE + header_len + padding) % VELO_ALIGNMENT == 0`
/// Note that the initial `HEADER_LEN_SIZE` comes from the length prefix in safetensors
/// format, but typically the "header length" we get is just the JSON bytes.
///
/// The standard safetensors layout is:
/// [u64: length_of_header] [header_bytes] [padding] [tensor_data]
///
/// The goal is for `tensor_data` to start at % VELO_ALIGNMENT == 0.
#[inline]
pub fn calculate_padding(header_len: usize) -> Result<usize, AlignmentError> {
    // SAFETY: Checked add to prevent overflow attacks (Council Review P0)
    let current_offset = HEADER_LEN_SIZE
        .checked_add(header_len)
        .ok_or(AlignmentError::HeaderTooLarge)?;

    let remainder = current_offset % VELO_ALIGNMENT;

    if remainder == 0 {
        Ok(0)
    } else {
        Ok(VELO_ALIGNMENT - remainder)
    }
}

/// Aligns a size up to the next provided boundary.
#[inline]
pub fn align_up(size: usize, boundary: usize) -> usize {
    if boundary == 0 || size == 0 {
        return size;
    }
    let remainder = size % boundary;
    if remainder == 0 {
        size
    } else {
        (size / boundary + 1) * boundary
    }
}

/// Aligns a size up to the next HugePage (2MB) boundary.
///
/// H-20 Invariant: `ftruncate` on hugetlbfs requires size to be a multiple of the page size.
#[inline]
pub fn align_to_huge_page(size: usize) -> usize {
    use crate::shm::constants::HUGE_PAGE_SIZE;
    align_up(size, HUGE_PAGE_SIZE)
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

    #[test]
    fn test_huge_page_alignment() {
        // H-20 Internal Logic Tests
        use crate::shm::constants::HUGE_PAGE_SIZE;

        // Case 1: Underflow (Small file) -> 2MB
        assert_eq!(align_to_huge_page(68), HUGE_PAGE_SIZE);
        assert_eq!(align_to_huge_page(1), HUGE_PAGE_SIZE);

        // Case 2: Exact Match -> 2MB
        assert_eq!(align_to_huge_page(HUGE_PAGE_SIZE), HUGE_PAGE_SIZE);

        // Case 3: Overflow -> 4MB
        assert_eq!(align_to_huge_page(HUGE_PAGE_SIZE + 1), HUGE_PAGE_SIZE * 2);

        // Case 4: Zero -> 0 (or 2MB? - Implementation choice, typically we want at least one page if non-zero)
        // Our implementation: if input is 0, (0 / 2M) * 2M = 0?
        // Logic: ((size / H) + 1) * H would represent "next boundary".
        // If size % H == 0, returns size. So 0 returns 0.
        // If the file is empty, we probably shouldn't allocate hugepages or minimal 2MB.
        assert_eq!(align_to_huge_page(0), 0);
    }

    #[test]
    fn test_align_up() {
        assert_eq!(align_up(0, 4096), 0);
        assert_eq!(align_up(1, 4096), 4096);
        assert_eq!(align_up(4096, 4096), 4096);
        assert_eq!(align_up(4097, 4096), 8192);
        assert_eq!(align_up(100, 0), 100);
    }
}
