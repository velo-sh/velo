//! Environment cache for fast startup.
//!
//! Caches Python's sys.path and other configuration to avoid
//! expensive filesystem scanning on subsequent runs.
//!
//! Uses rkyv for zero-copy deserialization - fastest possible cache loading.

use anyhow::{Context, Result};
use rkyv::{Archive, Deserialize, Serialize, rancor::Error as RkyvError};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const CACHE_FILE: &str = ".velo_cache/env.rkyv";

/// Cached environment configuration.
#[derive(Archive, Deserialize, Serialize, Debug, Clone)]
#[rkyv(compare(PartialEq), derive(Debug))]
pub struct EnvCache {
    /// SHA256 hash of uv.lock (environment fingerprint)
    pub fingerprint: String,
    /// Cached sys.path entries
    pub sys_path: Vec<String>,
    /// Cached PYTHONHOME
    pub python_home: String,
}

impl EnvCache {
    /// Compute fingerprint from uv.lock file.
    pub fn compute_fingerprint(project_dir: &Path) -> Option<String> {
        let lock_file = project_dir.join("uv.lock");
        if !lock_file.exists() {
            return None;
        }

        let content = fs::read(&lock_file).ok()?;
        let hash = Sha256::digest(&content);
        Some(hex::encode(hash))
    }

    /// Load cache from disk if fingerprint matches.
    /// Uses rkyv zero-copy deserialization for maximum speed.
    pub fn load(project_dir: &Path, current_fingerprint: &str) -> Option<Self> {
        let cache_path = project_dir.join(CACHE_FILE);
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
        let cache_path = project_dir.join(CACHE_FILE);
        let cache_dir = cache_path.parent().unwrap();

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
        project_dir.join(".velo_cache")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_fingerprint_computation() {
        let dir = tempdir().unwrap();
        let lock_file = dir.path().join("uv.lock");
        fs::write(&lock_file, "test content").unwrap();

        let fingerprint = EnvCache::compute_fingerprint(dir.path());
        assert!(fingerprint.is_some());
        assert_eq!(fingerprint.unwrap().len(), 64); // SHA256 hex length
    }

    #[test]
    fn test_cache_save_load() {
        let dir = tempdir().unwrap();
        let cache = EnvCache {
            fingerprint: "test123".to_string(),
            sys_path: vec!["/path/one".to_string(), "/path/two".to_string()],
            python_home: "/usr/local/python".to_string(),
        };

        cache.save(dir.path()).unwrap();

        let loaded = EnvCache::load(dir.path(), "test123");
        assert!(loaded.is_some());
        let loaded = loaded.unwrap();
        assert_eq!(loaded.fingerprint, "test123");
        assert_eq!(loaded.sys_path.len(), 2);
    }

    #[test]
    fn test_cache_fingerprint_mismatch() {
        let dir = tempdir().unwrap();
        let cache = EnvCache {
            fingerprint: "old_fingerprint".to_string(),
            sys_path: vec![],
            python_home: "".to_string(),
        };

        cache.save(dir.path()).unwrap();

        // Should return None if fingerprint doesn't match
        let loaded = EnvCache::load(dir.path(), "new_fingerprint");
        assert!(loaded.is_none());
    }
}
