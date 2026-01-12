//! Environment fingerprinting for convergence detection
//!
//! Tracks the state of pyproject.toml and uv.lock to detect when
//! the environment needs re-synchronization.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::custody::error::{CustodyError, Result};

/// Fingerprint of the project environment state
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EnvironmentFingerprint {
    /// BLAKE3 hash of pyproject.toml content
    pub pyproject_hash: String,
    /// BLAKE3 hash of uv.lock content (if exists)
    pub lock_hash: Option<String>,
    /// Velo build hash that created this state
    pub velo_hash: String,
    /// Timestamp of last sync
    pub synced_at: u64,
}

impl EnvironmentFingerprint {
    /// Compute fingerprint for a project directory
    pub fn compute(project_dir: &Path) -> Result<Self> {
        let pyproject_path = project_dir.join("pyproject.toml");
        let lock_path = project_dir.join("uv.lock");

        // Read and hash pyproject.toml
        let pyproject_content =
            fs::read_to_string(&pyproject_path).map_err(|e| CustodyError::StateFileError {
                path: pyproject_path.clone(),
                source: e,
            })?;
        let pyproject_hash = Self::hash_content(&pyproject_content);

        // Read and hash uv.lock if it exists
        let lock_hash = if lock_path.exists() {
            let lock_content =
                fs::read_to_string(&lock_path).map_err(|e| CustodyError::StateFileError {
                    path: lock_path.clone(),
                    source: e,
                })?;
            Some(Self::hash_content(&lock_content))
        } else {
            None
        };

        let synced_at = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        Ok(Self {
            pyproject_hash,
            lock_hash,
            velo_hash: crate::custody::velo_build_hash().to_string(),
            synced_at,
        })
    }

    /// Hash content using BLAKE3
    fn hash_content(content: &str) -> String {
        let hash = blake3::hash(content.as_bytes());
        hash.to_hex().to_string()
    }

    /// Check if this fingerprint matches another (ignoring timestamp)
    pub fn matches(&self, other: &Self) -> bool {
        self.pyproject_hash == other.pyproject_hash
            && self.lock_hash == other.lock_hash
            && self.velo_hash == other.velo_hash
    }
}

/// Environment state stored in .velo/env.state
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnvironmentState {
    /// Current fingerprint
    pub fingerprint: EnvironmentFingerprint,
    /// State of the environment
    pub status: EnvironmentStatus,
}

/// Status of the environment
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum EnvironmentStatus {
    /// Environment is ready and synchronized
    Ready,
    /// Environment needs synchronization
    Stale,
    /// Sync in progress
    Syncing,
    /// Error state (manual intervention needed)
    Error(String),
}

impl EnvironmentState {
    /// State file path for a project
    pub fn state_path(project_dir: &Path) -> PathBuf {
        project_dir.join(".velo").join("env.state")
    }

    /// Load state from file
    pub fn load(project_dir: &Path) -> Result<Option<Self>> {
        let path = Self::state_path(project_dir);
        if !path.exists() {
            return Ok(None);
        }

        let content = fs::read_to_string(&path).map_err(|e| CustodyError::StateFileError {
            path: path.clone(),
            source: e,
        })?;

        let state: Self =
            serde_json::from_str(&content).map_err(|e| CustodyError::StateFileError {
                path,
                source: std::io::Error::new(std::io::ErrorKind::InvalidData, e),
            })?;

        Ok(Some(state))
    }

    /// Save state to file
    pub fn save(&self, project_dir: &Path) -> Result<()> {
        let path = Self::state_path(project_dir);

        // Ensure .velo directory exists
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| CustodyError::StateFileError {
                path: parent.to_path_buf(),
                source: e,
            })?;
        }

        let content =
            serde_json::to_string_pretty(self).map_err(|e| CustodyError::StateFileError {
                path: path.clone(),
                source: std::io::Error::new(std::io::ErrorKind::InvalidData, e),
            })?;

        fs::write(&path, content).map_err(|e| CustodyError::StateFileError {
            path: path.clone(),
            source: e,
        })?;

        Ok(())
    }

    /// Check if environment needs sync
    pub fn needs_sync(&self, current: &EnvironmentFingerprint) -> bool {
        !self.fingerprint.matches(current) || self.status != EnvironmentStatus::Ready
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_fingerprint_compute() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");
        fs::write(&pyproject, "[project]\nname = \"test\"").unwrap();

        let fp = EnvironmentFingerprint::compute(tmp.path()).unwrap();

        assert!(!fp.pyproject_hash.is_empty());
        assert!(fp.lock_hash.is_none());
        assert!(!fp.velo_hash.is_empty());
    }

    #[test]
    fn test_fingerprint_matches() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");
        fs::write(&pyproject, "[project]\nname = \"test\"").unwrap();

        let fp1 = EnvironmentFingerprint::compute(tmp.path()).unwrap();
        let fp2 = EnvironmentFingerprint::compute(tmp.path()).unwrap();

        assert!(fp1.matches(&fp2));
    }

    #[test]
    fn test_fingerprint_detects_change() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");

        fs::write(&pyproject, "[project]\nname = \"test\"").unwrap();
        let fp1 = EnvironmentFingerprint::compute(tmp.path()).unwrap();

        fs::write(&pyproject, "[project]\nname = \"test2\"").unwrap();
        let fp2 = EnvironmentFingerprint::compute(tmp.path()).unwrap();

        assert!(!fp1.matches(&fp2));
    }

    #[test]
    fn test_state_save_load() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");
        fs::write(&pyproject, "[project]\nname = \"test\"").unwrap();

        let fp = EnvironmentFingerprint::compute(tmp.path()).unwrap();
        let state = EnvironmentState {
            fingerprint: fp.clone(),
            status: EnvironmentStatus::Ready,
        };

        state.save(tmp.path()).unwrap();

        let loaded = EnvironmentState::load(tmp.path()).unwrap().unwrap();
        assert!(loaded.fingerprint.matches(&fp));
        assert_eq!(loaded.status, EnvironmentStatus::Ready);
    }
}
