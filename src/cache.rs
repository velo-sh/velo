//! Environment cache for fast startup.
//!
//! Caches Python's sys.path and other configuration to avoid
//! expensive filesystem scanning on subsequent runs.
//!
//! Uses rkyv for zero-copy deserialization - fastest possible cache loading.

use anyhow::{Context, Result};
use rkyv::{Archive, Deserialize, Serialize, rancor::Error as RkyvError};
use std::fs;
use std::path::{Path, PathBuf};

pub use crate::common::paths::*;
use crate::python_info::PythonVersion;

const CACHE_FILE_NAME: &str = "env.rkyv";

/// Cache format version. Bump when struct changes.
pub const CACHE_VERSION: u32 = 2;

/// Environment variable relevant for Python execution.
#[derive(Archive, Deserialize, Serialize, Debug, Clone, PartialEq, Default)]
#[rkyv(compare(PartialEq), derive(Debug))]
pub struct EnvVar {
    pub name: String,
    pub value: String,
}

/// Cached environment configuration.
#[derive(Archive, Deserialize, Serialize, Debug, Clone)]
#[rkyv(compare(PartialEq), derive(Debug))]
pub struct EnvCache {
    // === Phase 1 (existing) ===
    /// BLAKE3 hash of uv.lock (environment fingerprint)
    pub fingerprint: String,
    /// Cached sys.path entries
    pub sys_path: Vec<String>,
    /// Cached PYTHONHOME
    pub python_home: String,

    // === Phase 1.5: ABI Compatibility ===
    /// Python version (major.minor.patch)
    pub python_version: PythonVersion,
    /// ABI tag like "cpython-311-darwin"
    pub abi_tag: String,
    /// Platform tag like "macosx_14_0_arm64"
    pub platform_tag: String,

    // === Phase 1.5: Environment Integrity ===
    /// BLAKE3 of sorted `pip freeze` output
    pub packages_hash: String,
    /// Critical environment variables
    pub critical_env_vars: Vec<EnvVar>,

    // === Phase 1.5: Metadata ===
    /// Unix timestamp when cache was created
    pub created_at: u64,
    /// Velo version that created this cache
    pub velo_version: String,
    /// Cache format version
    pub cache_version: u32,
}

impl EnvCache {
    /// Derive a stable 32-byte machine key for Keyed BLAKE3 (H-6).
    /// RFC-0008: Prevents cache sharing/spoofing between different machines.
    fn get_machine_key() -> [u8; 32] {
        // In production: derive from /etc/machine-id or similar
        // For now: use a stable hardware-bound string
        let mut key = [0u8; 32];
        let machine_id = hostname::get()
            .ok()
            .unwrap_or_else(|| "unknown-host".into());
        let hash = blake3::hash(machine_id.to_string_lossy().as_bytes());
        key.copy_from_slice(hash.as_bytes());
        key
    }

    /// Compute fingerprint from uv.lock file using Keyed BLAKE3 (H-6).
    pub fn compute_fingerprint(project_dir: &Path) -> Option<String> {
        let lock_file = VeloPaths::uv_lock(project_dir);
        if !lock_file.exists() {
            return None;
        }

        let content = fs::read(&lock_file).ok()?;
        let key = Self::get_machine_key();
        let hash = blake3::keyed_hash(&key, &content);
        Some(hash.to_hex().to_string())
    }

    /// Load cache from disk if fingerprint matches.
    /// Uses rkyv zero-copy deserialization for maximum speed.
    pub fn load(project_dir: &Path, current_fingerprint: &str) -> Option<Self> {
        let cache_path = VeloPaths::project_file(project_dir, VELO_CACHE_DIR).join(CACHE_FILE_NAME);
        let bytes = fs::read(&cache_path).ok()?;

        // Zero-copy access to archived data
        let archived = rkyv::access::<ArchivedEnvCache, RkyvError>(&bytes).ok()?;

        // Only return if fingerprint matches
        if archived.fingerprint == current_fingerprint {
            // Deserialize to owned struct
            rkyv::deserialize::<EnvCache, RkyvError>(archived).ok()
        } else {
            None
        }
    }

    /// Save cache to disk using rkyv binary format.
    pub fn save(&self, project_dir: &Path) -> Result<()> {
        let cache_path = VeloPaths::project_file(project_dir, VELO_CACHE_DIR).join(CACHE_FILE_NAME);
        let cache_dir = cache_path
            .parent()
            .ok_or_else(|| anyhow::anyhow!("Failed to determine cache directory parent"))?;

        fs::create_dir_all(cache_dir)
            .with_context(|| format!("Failed to create cache directory: {:?}", cache_dir))?;

        let bytes = rkyv::to_bytes::<RkyvError>(self)
            .map_err(|e| anyhow::anyhow!("Failed to serialize cache: {}", e))?;

        fs::write(&cache_path, &bytes)
            .with_context(|| format!("Failed to write cache: {:?}", cache_path))?;

        Ok(())
    }

    /// Get the cache directory path.
    #[allow(dead_code)]
    pub fn cache_dir(project_dir: &Path) -> PathBuf {
        VeloPaths::project_file(project_dir, VELO_CACHE_DIR)
    }

    /// Check if this cache is compatible with current Velo version.
    pub fn is_version_compatible(&self) -> bool {
        self.cache_version == CACHE_VERSION
    }

    /// Check if this cache is ABI-compatible with the given Python info.
    pub fn is_abi_compatible(&self, current_abi_tag: &str) -> bool {
        self.abi_tag == current_abi_tag
    }

    /// Create a new EnvCache with default Phase 1.5 fields.
    pub fn new(
        fingerprint: String,
        sys_path: Vec<String>,
        python_home: String,
        python_version: PythonVersion,
        abi_tag: String,
        platform_tag: String,
    ) -> Self {
        Self {
            fingerprint,
            sys_path,
            python_home,
            python_version,
            abi_tag,
            platform_tag,
            packages_hash: String::new(),
            critical_env_vars: Vec::new(),
            created_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0),
            velo_version: env!("CARGO_PKG_VERSION").to_string(),
            cache_version: CACHE_VERSION,
        }
    }

    /// Compute BLAKE3 hash of installed packages (pip freeze output).
    pub fn compute_packages_hash(python: &Path) -> Result<String> {
        use std::process::Command;

        let output = Command::new(python)
            .args(["-m", "pip", "freeze", "--local"])
            .output()
            .context("Failed to run pip freeze")?;

        if !output.status.success() {
            anyhow::bail!("pip freeze failed");
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut packages: Vec<&str> = stdout.lines().collect();
        packages.sort();

        let hash = blake3::hash(packages.join("\n").as_bytes());
        Ok(hash.to_hex().to_string())
    }

    /// Capture critical environment variables.
    pub fn capture_critical_env_vars() -> Vec<EnvVar> {
        const CRITICAL_ENV_VARS: &[&str] = &[
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONDONTWRITEBYTECODE",
            "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH",
            "CUDA_HOME",
            "CUDA_VISIBLE_DEVICES",
            "TORCH_HOME",
            "TRANSFORMERS_CACHE",
            "HF_HOME",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OMP_NUM_THREADS",
        ];

        CRITICAL_ENV_VARS
            .iter()
            .filter_map(|name| {
                std::env::var(name).ok().map(|value| EnvVar {
                    name: name.to_string(),
                    value,
                })
            })
            .collect()
    }

    /// Detect environment drift by comparing packages hash.
    pub fn detect_environment_drift(&self, python: &Path) -> Option<String> {
        if self.packages_hash.is_empty() {
            return None;
        }

        match Self::compute_packages_hash(python) {
            Ok(current_hash) => {
                if current_hash != self.packages_hash {
                    Some(format!(
                        "⚠️  Environment Drift Detected\n\
                         ├─ Packages have changed since last cache\n\
                         ├─ Cached hash:  {}...\n\
                         ├─ Current hash: {}...\n\
                         └─ Run `uv sync` to restore locked state",
                        &self.packages_hash[..16],
                        &current_hash[..16]
                    ))
                } else {
                    None
                }
            }
            Err(_) => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    /// Helper to create a test cache with minimal fields
    fn test_cache(fingerprint: &str) -> EnvCache {
        EnvCache::new(
            fingerprint.to_string(),
            vec!["/path/one".to_string(), "/path/two".to_string()],
            "/usr/local/python".to_string(),
            PythonVersion {
                major: 3,
                minor: 11,
                patch: 5,
            },
            "cpython-311-darwin".to_string(),
            "macosx_14_0_arm64".to_string(),
        )
    }

    #[test]
    fn test_fingerprint_computation() {
        let dir = tempdir().unwrap();
        let lock_file = VeloPaths::uv_lock(dir.path());
        fs::write(&lock_file, "test content").unwrap();

        let fingerprint = EnvCache::compute_fingerprint(dir.path());
        assert!(fingerprint.is_some());
        assert_eq!(fingerprint.unwrap().len(), 64); // BLAKE3 hex length
    }

    #[test]
    fn test_cache_save_load() {
        let dir = tempdir().unwrap();
        let cache = test_cache("test123");

        cache.save(dir.path()).unwrap();

        let loaded = EnvCache::load(dir.path(), "test123");
        assert!(loaded.is_some());
        let loaded = loaded.unwrap();
        assert_eq!(loaded.fingerprint, "test123");
        assert_eq!(loaded.sys_path.len(), 2);
        assert_eq!(loaded.python_version.major, 3);
        assert_eq!(loaded.python_version.minor, 11);
        assert_eq!(loaded.abi_tag, "cpython-311-darwin");
    }

    #[test]
    fn test_cache_fingerprint_mismatch() {
        let dir = tempdir().unwrap();
        let cache = test_cache("old_fingerprint");

        cache.save(dir.path()).unwrap();

        // Should return None if fingerprint doesn't match
        let loaded = EnvCache::load(dir.path(), "new_fingerprint");
        assert!(loaded.is_none());
    }

    // -------------------------------------------------------------------------
    // Phase 1.5 Tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_cache_version_compatibility() {
        let cache = test_cache("test");
        assert!(cache.is_version_compatible());
    }

    #[test]
    fn test_cache_abi_compatibility_same() {
        let cache = test_cache("test");
        assert!(cache.is_abi_compatible("cpython-311-darwin"));
    }

    #[test]
    fn test_cache_abi_compatibility_different() {
        let cache = test_cache("test");
        assert!(!cache.is_abi_compatible("cpython-312-darwin"));
    }

    #[test]
    fn test_cache_new_sets_metadata() {
        let cache = test_cache("test");
        assert_eq!(cache.cache_version, CACHE_VERSION);
        assert_eq!(cache.velo_version, env!("CARGO_PKG_VERSION"));
        assert!(cache.created_at > 0);
    }

    #[test]
    fn test_env_var_struct() {
        let env_var = EnvVar {
            name: "PYTHONPATH".to_string(),
            value: "/custom/path".to_string(),
        };
        assert_eq!(env_var.name, "PYTHONPATH");
    }

    // -------------------------------------------------------------------------
    // Week 4: Integrity Tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_capture_critical_env_vars() {
        // Set a known env var (unsafe in Rust 2024 edition)
        // SAFETY: This is a test and we're single-threaded
        unsafe {
            std::env::set_var("PYTHONPATH", "/test/path");
        }

        let env_vars = EnvCache::capture_critical_env_vars();

        // Should capture PYTHONPATH
        let pythonpath = env_vars.iter().find(|v| v.name == "PYTHONPATH");
        assert!(pythonpath.is_some());
        assert!(pythonpath.unwrap().value.contains("/test/path"));

        // Cleanup
        // SAFETY: This is a test and we're single-threaded
        unsafe {
            std::env::remove_var("PYTHONPATH");
        }
    }

    #[test]
    fn test_drift_detection_no_hash() {
        let cache = test_cache("test");
        // With empty packages_hash, should return None
        assert!(
            cache
                .detect_environment_drift(Path::new("/nonexistent"))
                .is_none()
        );
    }
}
