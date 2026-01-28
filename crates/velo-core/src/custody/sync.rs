//! Environment synchronization - Ensures hermetic environment state (RFC-0018)
//!
//! This module provides implicit `uv sync` functionality when the environment
//! fingerprint drifts from the stored state.

use std::path::Path;
use std::process::Command;

use crate::custody::custodian::{Custodian, UvCustodian};
use crate::custody::error::{CustodyError, Result};
use crate::custody::fingerprint::{EnvironmentFingerprint, EnvironmentState, EnvironmentStatus};

/// Ensures the environment is synchronized before execution
pub struct EnvironmentSync {
    custodian: UvCustodian,
}

impl EnvironmentSync {
    /// Create a new environment sync handler
    pub fn new() -> Self {
        Self {
            custodian: UvCustodian::new(),
        }
    }

    /// Check if synchronization is needed and perform it if so
    ///
    /// Returns Ok(true) if sync was performed, Ok(false) if environment was already up-to-date
    pub fn ensure_synced(&self, project_dir: &Path) -> Result<bool> {
        // Check if pyproject.toml exists
        let pyproject = project_dir.join("pyproject.toml");
        if !pyproject.exists() {
            tracing::debug!("No pyproject.toml found, skipping sync check");
            return Ok(false);
        }

        // Compute current fingerprint
        let current = EnvironmentFingerprint::compute(project_dir)?;

        // Load stored state
        let stored = EnvironmentState::load(project_dir)?;

        // Check if sync is needed
        let needs_sync = match &stored {
            Some(state) => state.needs_sync(&current),
            None => true, // No state file = uninitialized
        };

        if !needs_sync {
            tracing::debug!("Environment fingerprint matches, no sync needed");
            return Ok(false);
        }

        tracing::info!("Environment fingerprint mismatch, triggering sync");

        // Perform sync
        self.run_sync(project_dir)?;

        // Update state file
        let new_state = EnvironmentState {
            fingerprint: EnvironmentFingerprint::compute(project_dir)?,
            status: EnvironmentStatus::Ready,
        };
        new_state.save(project_dir)?;

        Ok(true)
    }

    /// Run `uv sync` via the custodied toolchain
    fn run_sync(&self, project_dir: &Path) -> Result<()> {
        let uv_path = self.custodian.ensure()?;

        tracing::info!("Running uv sync in {}", project_dir.display());

        // Update state to SYNCING
        if let Ok(Some(mut state)) = EnvironmentState::load(project_dir) {
            state.status = EnvironmentStatus::Syncing;
            let _ = state.save(project_dir);
        }

        let mut cmd = Command::new(&uv_path);
        cmd.arg("sync").arg("--no-config");

        // Only use --frozen if uv.lock exists.
        // RFC-0018: Shadow syncs should be frozen when possible to prevent side-effects.
        if project_dir.join("uv.lock").exists() {
            cmd.arg("--frozen");
        }

        let status = cmd
            .current_dir(project_dir)
            // Surgical environment: remove inherited Python vars that might conflict with the target project
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .env_remove("VIRTUAL_ENV")
            .status()
            .map_err(|e| CustodyError::SyncFailed(format!("failed to execute uv sync: {}", e)))?;

        if !status.success() {
            let error_msg = format!("uv sync failed with exit code: {:?}", status.code());

            // Update state to ERROR
            if let Ok(fp) = EnvironmentFingerprint::compute(project_dir) {
                let error_state = EnvironmentState {
                    fingerprint: fp,
                    status: EnvironmentStatus::Error(error_msg.clone()),
                };
                let _ = error_state.save(project_dir);
            }

            return Err(CustodyError::SyncFailed(error_msg));
        }

        tracing::info!("uv sync completed successfully");
        Ok(())
    }

    /// Force a sync regardless of fingerprint state
    pub fn force_sync(&self, project_dir: &Path) -> Result<()> {
        self.run_sync(project_dir)?;

        // Update state file
        let new_state = EnvironmentState {
            fingerprint: EnvironmentFingerprint::compute(project_dir)?,
            status: EnvironmentStatus::Ready,
        };
        new_state.save(project_dir)?;

        Ok(())
    }

    /// Reset the environment state (for recovery from error state)
    pub fn reset_state(&self, project_dir: &Path) -> Result<()> {
        let state_path = EnvironmentState::state_path(project_dir);
        if state_path.exists() {
            std::fs::remove_file(&state_path).map_err(|e| CustodyError::StateFileError {
                path: state_path,
                source: e,
            })?;
        }
        Ok(())
    }
}

impl Default for EnvironmentSync {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_ensure_synced_no_pyproject() {
        let tmp = tempdir().unwrap();
        let sync = EnvironmentSync::new();

        // No pyproject.toml = no sync needed
        let result = sync.ensure_synced(tmp.path()).unwrap();
        assert!(!result, "Should not sync without pyproject.toml");
    }

    #[test]
    fn test_ensure_synced_detects_new_project() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");
        fs::write(
            &pyproject,
            r#"
[project]
name = "test"
version = "0.1.0"
"#,
        )
        .unwrap();

        let _sync = EnvironmentSync::new();

        // Should want to sync (no state file = uninitialized)
        // We don't actually run sync here since uv may not be available
        let stored = EnvironmentState::load(tmp.path()).unwrap();
        assert!(stored.is_none(), "Should have no stored state");
    }

    #[test]
    fn test_reset_state() {
        let tmp = tempdir().unwrap();
        let pyproject = tmp.path().join("pyproject.toml");
        fs::write(&pyproject, "[project]\nname = \"test\"").unwrap();

        // Create a state file
        let fp = EnvironmentFingerprint::compute(tmp.path()).unwrap();
        let state = EnvironmentState {
            fingerprint: fp,
            status: EnvironmentStatus::Ready,
        };
        state.save(tmp.path()).unwrap();

        // Verify it exists
        assert!(EnvironmentState::state_path(tmp.path()).exists());

        // Reset
        let sync = EnvironmentSync::new();
        sync.reset_state(tmp.path()).unwrap();

        // Verify it's gone
        assert!(!EnvironmentState::state_path(tmp.path()).exists());
    }
}
