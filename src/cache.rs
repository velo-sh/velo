//! Environment cache for fast startup.
//!
//! Caches Python's sys.path and other configuration to avoid
//! expensive filesystem scanning on subsequent runs.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const CACHE_FILE: &str = ".velo_cache/env.json";

/// Cached environment configuration.
#[derive(Debug, Serialize, Deserialize)]
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
    pub fn load(project_dir: &Path, current_fingerprint: &str) -> Option<Self> {
        let cache_path = project_dir.join(CACHE_FILE);
        let content = fs::read_to_string(&cache_path).ok()?;
        let cache: EnvCache = serde_json::from_str(&content).ok()?;

        // Only return if fingerprint matches
        if cache.fingerprint == current_fingerprint {
            Some(cache)
        } else {
            None
        }
    }

    /// Save cache to disk.
    pub fn save(&self, project_dir: &Path) -> Result<()> {
        let cache_path = project_dir.join(CACHE_FILE);
        let cache_dir = cache_path.parent().unwrap();

        fs::create_dir_all(cache_dir)
            .with_context(|| format!("Failed to create cache directory: {:?}", cache_dir))?;

        let content = serde_json::to_string_pretty(self)?;
        fs::write(&cache_path, content)
            .with_context(|| format!("Failed to write cache: {:?}", cache_path))?;

        Ok(())
    }

    /// Get the cache directory path.
    pub fn cache_dir(project_dir: &Path) -> PathBuf {
        project_dir.join(".velo_cache")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
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
