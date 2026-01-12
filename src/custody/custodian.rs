//! Custodian trait and UvCustodian implementation
//!
//! The Custodian manages the lifecycle of embedded toolchain binaries:
//! - Extraction to versioned paths
//! - Integrity verification via BLAKE3
//! - Execution with surgical environment

use std::fs::{self, File, Permissions};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::{Command, ExitStatus};

use crate::custody::asset::UvAsset;
use crate::custody::error::{CustodyError, Result};
use crate::custody::velo_build_hash;

/// Trait defining the contract for embedded binary custody
pub trait Custodian {
    /// Returns the target extraction path including build-hash
    fn target_path(&self) -> PathBuf;

    /// Check if toolchain is already extracted and valid
    fn is_ready(&self) -> bool;

    /// Verifies the integrity of the extracted asset
    fn verify(&self) -> Result<bool>;

    /// Atomic extraction of the embedded bytes to the target path
    fn extract(&self) -> Result<()>;

    /// Ensure the toolchain is ready (extract if needed, verify)
    fn ensure(&self) -> Result<PathBuf>;

    /// Executes a managed command through the toolchain context
    fn execute(&self, args: &[&str]) -> Result<ExitStatus>;
}

/// Custodian implementation for the embedded uv toolchain
pub struct UvCustodian {
    /// Base directory for Velo data (~/.velo)
    base_dir: PathBuf,
    /// Cached asset reference (used when embedded_uv feature is enabled)
    #[allow(dead_code)]
    asset: Option<UvAsset>,
}

impl UvCustodian {
    /// Create a new UvCustodian with default paths
    pub fn new() -> Self {
        let base_dir = dirs::home_dir()
            .map(|h| h.join(".velo"))
            .unwrap_or_else(|| PathBuf::from("/tmp/.velo"));

        Self {
            base_dir,
            asset: None,
        }
    }

    /// Create with custom base directory (for testing)
    pub fn with_base_dir(base_dir: PathBuf) -> Self {
        Self {
            base_dir,
            asset: None,
        }
    }

    /// Get the bin directory for the current build
    fn bin_dir(&self) -> PathBuf {
        self.base_dir.join("bin").join(velo_build_hash())
    }

    /// Get path to the uv binary
    fn uv_path(&self) -> PathBuf {
        self.bin_dir().join("uv")
    }

    /// Use system uv as fallback when embedded is not available
    fn find_system_uv(&self) -> Option<PathBuf> {
        // Check common locations
        let candidates = [
            // User-installed via cargo
            dirs::home_dir().map(|h| h.join(".cargo/bin/uv")),
            // Homebrew on macOS
            Some(PathBuf::from("/opt/homebrew/bin/uv")),
            // Linux system install
            Some(PathBuf::from("/usr/local/bin/uv")),
            Some(PathBuf::from("/usr/bin/uv")),
        ];

        for candidate in candidates.into_iter().flatten() {
            if candidate.exists() {
                return Some(candidate);
            }
        }

        // Try PATH lookup
        which::which("uv").ok()
    }
}

impl Default for UvCustodian {
    fn default() -> Self {
        Self::new()
    }
}

impl Custodian for UvCustodian {
    fn target_path(&self) -> PathBuf {
        self.uv_path()
    }

    fn is_ready(&self) -> bool {
        let path = self.uv_path();
        path.exists() && path.is_file()
    }

    fn verify(&self) -> Result<bool> {
        let path = self.uv_path();

        if !path.exists() {
            return Ok(false);
        }

        // Check basic file properties first
        let metadata = fs::metadata(&path).map_err(|e| CustodyError::StateFileError {
            path: path.clone(),
            source: e,
        })?;

        // Check it's a regular file with execute permission
        let perms = metadata.permissions();
        let is_executable = perms.mode() & 0o111 != 0;

        if !is_executable {
            return Ok(false);
        }

        // BLAKE3 integrity verification (RFC-0018 §3.2)
        // Only verify if embedded_uv feature is enabled and we have an expected hash
        #[cfg(feature = "embedded_uv")]
        {
            use std::io::Read;

            let asset = match UvAsset::current() {
                Ok(a) => a,
                Err(_) => return Ok(is_executable), // Fall back to basic check
            };

            let expected_hash = asset.expected_hash();
            if expected_hash.is_empty() {
                // No hash to verify against
                return Ok(is_executable);
            }

            // Compute BLAKE3 hash of the extracted binary
            let mut file = fs::File::open(&path).map_err(|e| CustodyError::StateFileError {
                path: path.clone(),
                source: e,
            })?;

            let mut hasher = blake3::Hasher::new();
            let mut buffer = [0u8; 65536]; // 64KB buffer

            loop {
                let bytes_read =
                    file.read(&mut buffer)
                        .map_err(|e| CustodyError::StateFileError {
                            path: path.clone(),
                            source: e,
                        })?;
                if bytes_read == 0 {
                    break;
                }
                hasher.update(&buffer[..bytes_read]);
            }

            let computed_hash = hasher.finalize().to_hex().to_string();

            if computed_hash != expected_hash {
                tracing::warn!(
                    "BLAKE3 mismatch: expected {}, got {}",
                    expected_hash,
                    computed_hash
                );
                return Ok(false);
            }

            tracing::debug!("BLAKE3 verification passed: {}", &computed_hash[..16]);
        }

        Ok(true)
    }

    fn extract(&self) -> Result<()> {
        let asset = UvAsset::current()?;
        let bytes = asset.bytes()?;

        let bin_dir = self.bin_dir();
        let target = self.uv_path();
        let temp_path = bin_dir.join("uv.tmp");

        // Atomic extraction protocol (RFC-0018 §3.1):
        // 1. Create directory with restricted permissions
        fs::create_dir_all(&bin_dir).map_err(|e| CustodyError::ExtractionFailed {
            path: bin_dir.clone(),
            source: e,
        })?;

        // Set directory to 0o700
        fs::set_permissions(&bin_dir, Permissions::from_mode(0o700)).map_err(|e| {
            CustodyError::ExtractionFailed {
                path: bin_dir.clone(),
                source: e,
            }
        })?;

        // 2. Write to temporary file
        let mut file = File::create(&temp_path).map_err(|e| CustodyError::ExtractionFailed {
            path: temp_path.clone(),
            source: e,
        })?;

        file.write_all(bytes)
            .map_err(|e| CustodyError::ExtractionFailed {
                path: temp_path.clone(),
                source: e,
            })?;

        file.flush().map_err(|e| CustodyError::ExtractionFailed {
            path: temp_path.clone(),
            source: e,
        })?;

        // 3. Set executable permissions (0o755)
        fs::set_permissions(&temp_path, Permissions::from_mode(0o755)).map_err(|e| {
            CustodyError::ExtractionFailed {
                path: temp_path.clone(),
                source: e,
            }
        })?;

        // 4. Atomic rename
        fs::rename(&temp_path, &target).map_err(|e| CustodyError::ExtractionFailed {
            path: target.clone(),
            source: e,
        })?;

        Ok(())
    }

    fn ensure(&self) -> Result<PathBuf> {
        // First, check if embedded uv is available and extracted
        if UvAsset::is_available() {
            if !self.is_ready() {
                self.extract()?;
            }

            if self.verify()? {
                return Ok(self.uv_path());
            }

            // Verification failed, try re-extraction
            self.extract()?;
            if self.verify()? {
                return Ok(self.uv_path());
            }

            return Err(CustodyError::IntegrityFailed {
                path: self.uv_path(),
                expected: "valid executable".to_string(),
                actual: "verification failed after re-extraction".to_string(),
            });
        }

        // Fallback: use system uv if available
        if let Some(system_uv) = self.find_system_uv() {
            tracing::debug!(
                "Using system uv at {} (embedded not available)",
                system_uv.display()
            );
            return Ok(system_uv);
        }

        Err(CustodyError::ToolchainNotFound(self.uv_path()))
    }

    fn execute(&self, args: &[&str]) -> Result<ExitStatus> {
        let uv_path = self.ensure()?;

        let status = Command::new(&uv_path)
            .args(args)
            // Surgical environment: remove potential pollutants
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .env_remove("PIP_INDEX_URL")
            .env_remove("PIP_EXTRA_INDEX_URL")
            .status()
            .map_err(|e| CustodyError::ExecutionFailed(format!("failed to execute uv: {}", e)))?;

        Ok(status)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_uv_custodian_default_paths() {
        let custodian = UvCustodian::new();
        let path = custodian.target_path();

        // Should be under ~/.velo/bin/{hash}/uv
        assert!(path.to_string_lossy().contains(".velo"));
        assert!(path.to_string_lossy().contains("bin"));
        assert!(path.to_string_lossy().ends_with("uv"));
    }

    #[test]
    fn test_uv_custodian_custom_base() {
        let tmp = tempdir().unwrap();
        let custodian = UvCustodian::with_base_dir(tmp.path().to_path_buf());
        let path = custodian.target_path();

        assert!(path.starts_with(tmp.path()));
    }

    #[test]
    fn test_is_ready_false_when_not_extracted() {
        let tmp = tempdir().unwrap();
        let custodian = UvCustodian::with_base_dir(tmp.path().to_path_buf());

        assert!(!custodian.is_ready());
    }

    #[test]
    fn test_find_system_uv() {
        let custodian = UvCustodian::new();
        // This may or may not find uv depending on the system
        let _ = custodian.find_system_uv();
    }
}
