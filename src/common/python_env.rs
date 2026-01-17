//! Python Environment Configuration - Single Source of Truth (SSOT)
//!
//! SPEC-0005: This module is the ONLY place that determines Python environment paths.
//!
//! ## Usage
//!
//! ```rust,ignore
//! use velo::common::python_env::PythonEnv;
//!
//! // Detect from Python path (one-time cost)
//! let env = PythonEnv::detect(python_path)?;
//!
//! // Apply to Command before spawn
//! env.apply_to_command(&mut cmd);
//!
//! // Or apply to current process (for worker self-init)
//! env.apply_to_process();
//! ```
//!
//! ## Consumers
//!
//! - `src/serve/worker.rs::spawn_native()` - set env before spawning
//! - `src/granian/worker_entry.rs::fixup_python_path()` - read and apply at worker startup

use std::path::{Path, PathBuf};

/// Python environment configuration (SSOT).
#[derive(Debug, Clone)]
pub struct PythonEnv {
    /// Python base prefix (where stdlib lives, e.g., /opt/homebrew/Cellar/python@3.11/...)
    pub base_prefix: PathBuf,

    /// Python version string (e.g., "3.11")
    pub version: String,

    /// Library directory (e.g., {base_prefix}/lib/python3.11)
    pub lib_dir: PathBuf,

    /// lib-dynload directory for C extensions (e.g., {lib_dir}/lib-dynload)
    pub lib_dynload: PathBuf,

    /// Virtual environment root (if applicable)
    pub venv_root: Option<PathBuf>,
}

impl PythonEnv {
    /// Detect Python environment from the Python executable path.
    ///
    /// Priority:
    /// 1. PEP 405 pyvenv.cfg (fastest, no subprocess)
    /// 2. Query Python's sys.base_prefix (fallback)
    ///
    /// Uses SSOT constants from config/constants.toml via build.rs generated code.
    pub fn detect(python_path: &Path) -> anyhow::Result<Self> {
        use crate::common::constants::{
            PYTHON_LIB_DIR_PATTERN, PYTHON_LIB_DYNLOAD_SUBDIR, PYTHON_VENV_PATH,
        };

        // Step 1: Find Project Root (SPEC-0005)
        let project_root = Self::find_project_root(python_path).ok_or_else(|| {
            anyhow::anyhow!("Failed to identify project root (missing pyproject.toml)")
        })?;

        // Step 2: Detect base_prefix
        let base_prefix = Self::detect_base_prefix(python_path)?;

        // Step 3: Detect Python version
        let version = Self::detect_version(python_path)?;

        // Step 4: Build paths using SSOT patterns
        // SSOT: PYTHON_LIB_DIR_PATTERN = "lib/python{version}"
        let lib_dir_relative = PYTHON_LIB_DIR_PATTERN.replace("{version}", &version);
        let lib_dir = base_prefix.join(&lib_dir_relative);
        // SSOT: PYTHON_LIB_DYNLOAD_SUBDIR = "lib-dynload"
        let lib_dynload = lib_dir.join(PYTHON_LIB_DYNLOAD_SUBDIR);

        // Step 5: Anchor venv root to project root (SPEC-0005)
        // SSOT: venv_path = ".venv" (from constants.toml)
        let venv_root_path = project_root.join(PYTHON_VENV_PATH);
        let venv_root = if venv_root_path.join("pyvenv.cfg").exists() {
            Some(venv_root_path)
        } else {
            None
        };

        Ok(Self {
            base_prefix,
            version,
            lib_dir,
            lib_dynload,
            venv_root,
        })
    }

    /// Find project root by searching for pyproject.toml upwards from python_path.
    fn find_project_root(start_path: &Path) -> Option<PathBuf> {
        use crate::common::constants::PYPROJECT_TOML;
        let mut current = start_path.to_path_buf();
        while let Some(parent) = current.parent() {
            if parent.join(PYPROJECT_TOML).exists() {
                return Some(parent.to_path_buf());
            }
            current = parent.to_path_buf();
        }
        None
    }

    /// Detect base_prefix using PEP 405 or Python subprocess.
    fn detect_base_prefix(python_path: &Path) -> anyhow::Result<PathBuf> {
        // Try PEP 405 first (pyvenv.cfg)
        if let Some(venv_root) = python_path.parent().and_then(|p| p.parent()) {
            let pyvenv_cfg = venv_root.join("pyvenv.cfg");
            if pyvenv_cfg.exists()
                && let Some(base) = Self::parse_pyvenv_cfg(&pyvenv_cfg)
            {
                log::debug!("[SSOT] base_prefix from pyvenv.cfg: {:?}", base);
                return Ok(base);
            }
        }

        // Fallback: Query Python directly
        let output = std::process::Command::new(python_path)
            .args(["-c", "import sys; print(sys.base_prefix)"])
            .output()
            .map_err(|e| anyhow::anyhow!("Failed to query Python: {}", e))?;

        if !output.status.success() {
            anyhow::bail!("Python subprocess failed");
        }

        let base = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if base.is_empty() {
            anyhow::bail!("Empty base_prefix from Python");
        }

        log::debug!("[SSOT] base_prefix from subprocess: {}", base);
        Ok(PathBuf::from(base))
    }

    /// Parse pyvenv.cfg to extract 'home' key and derive base_prefix.
    fn parse_pyvenv_cfg(path: &Path) -> Option<PathBuf> {
        let content = std::fs::read_to_string(path).ok()?;
        for line in content.lines() {
            if let Some(rest) = line.strip_prefix("home")
                && let Some(value) = rest.trim_start().strip_prefix('=')
            {
                // 'home' points to bin dir, we need parent for base_prefix
                let home = value.trim();
                return std::path::Path::new(home).parent().map(|p| p.to_path_buf());
            }
        }
        None
    }

    /// Detect Python version (major.minor).
    fn detect_version(python_path: &Path) -> anyhow::Result<String> {
        let output = std::process::Command::new(python_path)
            .args([
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ])
            .output()
            .map_err(|e| anyhow::anyhow!("Failed to query Python version: {}", e))?;

        if !output.status.success() {
            anyhow::bail!("Python version query failed");
        }

        let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if version.is_empty() {
            anyhow::bail!("Empty version from Python");
        }

        log::debug!("[SSOT] Python version: {}", version);
        Ok(version)
    }

    /// Apply environment to a Command before spawning a child process.
    pub fn apply_to_command(&self, cmd: &mut std::process::Command) {
        // PYTHONHOME: Required for PyO3 to find stdlib
        cmd.env("PYTHONHOME", &self.base_prefix);
        log::debug!("[SSOT] Set PYTHONHOME to: {:?}", self.base_prefix);

        // VELO_PYTHON_LIB_DIR: For worker_entry.rs to fixup sys.path
        cmd.env("VELO_PYTHON_LIB_DIR", &self.lib_dir);

        // VELO_PYTHON_LIB_DYNLOAD: For C extension modules
        if self.lib_dynload.exists() {
            cmd.env("VELO_PYTHON_LIB_DYNLOAD", &self.lib_dynload);
        }

        // VIRTUAL_ENV: If applicable
        if let Some(ref venv) = self.venv_root {
            cmd.env("VIRTUAL_ENV", venv);
        }
    }

    /// Apply environment to the current process (for workers that need to self-init).
    ///
    /// # Safety
    /// This function modifies environment variables, which is unsafe in Rust 2024 edition.
    /// It should only be called from single-threaded worker initialization code.
    pub fn apply_to_process(&self) {
        // SAFETY: Called from single-threaded worker initialization before any other threads
        unsafe {
            std::env::set_var("PYTHONHOME", &self.base_prefix);
            std::env::set_var("VELO_PYTHON_LIB_DIR", &self.lib_dir);

            if self.lib_dynload.exists() {
                std::env::set_var("VELO_PYTHON_LIB_DYNLOAD", &self.lib_dynload);
            }

            if let Some(ref venv) = self.venv_root {
                std::env::set_var("VIRTUAL_ENV", venv);
            }
        }

        log::debug!("[SSOT] Applied Python environment to current process");
    }

    /// Create from environment variables (used by worker_entry.rs).
    ///
    /// This reads the SSOT env vars set by the parent process.
    pub fn from_env() -> Option<Self> {
        let base_prefix = std::env::var("PYTHONHOME").ok()?;
        let lib_dir = std::env::var("VELO_PYTHON_LIB_DIR").ok()?;
        let lib_dynload = std::env::var("VELO_PYTHON_LIB_DYNLOAD").ok();
        let venv_root = std::env::var("VIRTUAL_ENV").ok();

        // Extract version from lib_dir (e.g., "python3.11" -> "3.11")
        let version = lib_dir
            .rsplit('/')
            .find(|s| s.starts_with("python"))
            .and_then(|s| s.strip_prefix("python"))
            .unwrap_or("3.11")
            .to_string();

        Some(Self {
            base_prefix: PathBuf::from(base_prefix),
            version,
            lib_dir: PathBuf::from(lib_dir),
            lib_dynload: lib_dynload.map(PathBuf::from).unwrap_or_default(),
            venv_root: venv_root.map(PathBuf::from),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_pyvenv_cfg() {
        let temp_dir = tempfile::tempdir().unwrap();
        let cfg_path = temp_dir.path().join("pyvenv.cfg");
        std::fs::write(
            &cfg_path,
            "home = /opt/homebrew/Cellar/python@3.11/3.11.5/bin\ninclude-system-site-packages = false\n",
        )
        .unwrap();

        let result = PythonEnv::parse_pyvenv_cfg(&cfg_path);
        assert!(result.is_some());
        let base = result.unwrap();
        assert!(base.to_string_lossy().contains("3.11.5"));
    }

    #[test]
    fn test_from_env_none_when_missing() {
        // Ensure env vars are not set
        // SAFETY: Test code, single-threaded
        unsafe {
            std::env::remove_var("PYTHONHOME");
            std::env::remove_var("VELO_PYTHON_LIB_DIR");
        }

        let result = PythonEnv::from_env();
        assert!(result.is_none());
    }
}
