//! Memory Subsystem Error Types
//!
//! H-32: Error Typing Discipline
//! Low-level modules should expose specific error types to allow
//! upper layers to implement differentiated recovery strategies.

use thiserror::Error;

/// Errors that can occur during shared memory operations.
#[derive(Error, Debug)]
pub enum MemoryError {
    /// Failed to create shared memory segment (memfd_create or shm_open)
    #[error("Failed to create shared memory segment: {0}")]
    SegmentCreationFailed(String),

    /// Failed to resize the shared memory segment (ftruncate)
    #[error("Failed to resize segment: {0}")]
    ResizeFailed(String),

    /// Failed to map memory (mmap)
    #[error("Failed to map memory: {0}")]
    MmapFailed(String),

    /// Failed to apply seals (fcntl F_ADD_SEALS)
    #[error("Failed to seal memory: {0}")]
    SealFailed(String),

    /// NUMA binding failed (H-30 strict mode)
    #[error("NUMA binding failed (H-30): {0}")]
    NumaBindFailed(String),

    /// Source file is invalid or too small
    #[error("InvalidSourceFile: {0}")]
    InvalidSourceFile(String),

    /// Header parsing failed (H-29 alignment)
    #[error("HeaderParseFailed: {0}")]
    HeaderParseFailed(String),

    /// Alignment calculation error
    #[error("Alignment error: {0}")]
    AlignmentError(#[from] super::util_alignment::AlignmentError),

    /// Invalid SHM name (e.g., contains NUL byte)
    #[error("Invalid SHM name: {0}")]
    InvalidName(String),
}

impl MemoryError {
    /// Returns true if this error is likely transient and retryable.
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            MemoryError::SegmentCreationFailed(_) | MemoryError::MmapFailed(_)
        )
    }

    /// Returns true if this error indicates a permission issue.
    pub fn is_permission_error(&self) -> bool {
        match self {
            MemoryError::SegmentCreationFailed(msg) | MemoryError::MmapFailed(msg) => {
                msg.contains("Permission denied") || msg.contains("EACCES")
            }
            _ => false,
        }
    }

    /// Returns true if this error indicates resource exhaustion.
    pub fn is_resource_exhaustion(&self) -> bool {
        match self {
            MemoryError::SegmentCreationFailed(msg) | MemoryError::MmapFailed(msg) => {
                msg.contains("Cannot allocate") || msg.contains("ENOMEM")
            }
            _ => false,
        }
    }
}
