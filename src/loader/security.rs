//! Security validation for bundle loading
//!
//! RFC-0006 Handover Section 2: Security red lines

use crate::loader::error::{LoaderError, Result};
use std::path::Path;

/// Default maximum bundle size: 256MB (DoS prevention)
///
/// Handover Section 2.2: Memory limits
pub const DEFAULT_MAX_BUNDLE_SIZE: u64 = 256 * 1024 * 1024;

/// Validate bundle file size before reading
///
/// MUST be called BEFORE reading the file to prevent OOM DoS.
pub fn validate_size(path: &Path, limit: u64) -> Result<()> {
    let metadata = std::fs::metadata(path)?;
    let size = metadata.len();

    if size > limit {
        return Err(LoaderError::BundleTooLarge { size, limit });
    }

    Ok(())
}

/// Validate file permissions (Unix only)
///
/// Handover Section 2.3: Reject world-writable files
#[cfg(unix)]
pub fn validate_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;

    let metadata = std::fs::metadata(path)?;
    let mode = metadata.permissions().mode();

    // Check for world-writable (mode & 0o002 != 0)
    if mode & 0o002 != 0 {
        return Err(LoaderError::InsecurePermissions {
            path: path.to_path_buf(),
            mode,
        });
    }

    Ok(())
}

/// Validate file permissions (non-Unix stub)
#[cfg(not(unix))]
pub fn validate_permissions(_path: &Path) -> Result<()> {
    // Windows: different permission model, implement later
    Ok(())
}

/// Validate bundle location is not in insecure directory
///
/// Handover Section 2.3: Reject /tmp and shared directories
/// Uses canonicalize() to prevent symlink traversal attacks
pub fn validate_location(path: &Path) -> Result<()> {
    let insecure_prefixes = ["/tmp", "/var/tmp", "/dev/shm"];

    // Ritual Layer 1: Raw Path Analysis
    // Reject obvious insecure prefixes in the input string
    let raw_path_str = path.to_string_lossy();
    for prefix in &insecure_prefixes {
        if raw_path_str.starts_with(prefix) {
            return Err(LoaderError::InsecureLocation {
                path: path.to_path_buf(),
            });
        }
    }

    // Ritual Layer 2: Symlink Target Verification
    // If the path is a symlink, check where it points BEFORE resolution
    #[cfg(unix)]
    if path.is_symlink() {
        #[allow(clippy::collapsible_if)]
        if let Ok(target) = std::fs::read_link(path) {
            let target_str = target.to_string_lossy();
            for prefix in &insecure_prefixes {
                if target_str.starts_with(prefix) {
                    return Err(LoaderError::InsecureLocation {
                        path: path.to_path_buf(),
                    });
                }
            }
        }
    }

    // Ritual Layer 3: Canonical Resolution (Root-of-Trust)
    // resolve all symlinks and ".." to find the actual physical location
    if let Ok(canonical) = path.canonicalize() {
        let canonical_str = canonical.to_string_lossy();
        for prefix in &insecure_prefixes {
            if canonical_str.starts_with(prefix) {
                return Err(LoaderError::InsecureLocation { path: canonical });
            }
        }
    } else if let Some(parent) = path.parent() {
        // Fallback for non-existent files: validate the parent directory
        if let Ok(canonical_parent) = parent.canonicalize() {
            let parent_str = canonical_parent.to_string_lossy();
            for prefix in &insecure_prefixes {
                if parent_str.starts_with(prefix) {
                    return Err(LoaderError::InsecureLocation {
                        path: path.to_path_buf(),
                    });
                }
            }
        }
    }

    Ok(())
}

/// Run all security validations
///
/// This is the main entry point for security checks.
/// Order matters: size → permissions → location
pub fn validate_all(path: &Path, limit: u64) -> Result<()> {
    validate_size(path, limit)?;
    validate_permissions(path)?;
    validate_location(path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_max_bundle_size_constant() {
        assert_eq!(DEFAULT_MAX_BUNDLE_SIZE, 256 * 1024 * 1024);
        assert_eq!(DEFAULT_MAX_BUNDLE_SIZE, 268_435_456);
    }
}
