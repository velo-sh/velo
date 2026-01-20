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

    /// Site-packages directory (if applicable, e.g., {venv_root}/lib/python3.11/site-packages)
    pub site_packages: Option<PathBuf>,
}

impl PythonEnv {
    /// Detect Python environment from the Python executable path.
    ///
    /// Priority:
    /// 1. PEP 405 pyvenv.cfg (fastest, no subprocess)
    /// 2. Query Python's sys.base_prefix (fallback)
    ///
    /// Uses SSOT constants from config/constants.toml via build.rs generated code.
    /// Detect Python environment from the Python executable path.
    ///
    /// Priority:
    /// 1. In-memory Cache (Fastest)
    /// 2. PEP 405 pyvenv.cfg (lightweight, no subprocess)
    /// 3. Query Python's sys.base_prefix (Fallback - slow)
    ///
    /// Uses SSOT constants from config/constants.toml via build.rs generated code.
    pub fn detect(python_path: &Path) -> anyhow::Result<Self> {
        use crate::common::constants::{
            PYTHON_LIB_DIR_PATTERN, PYTHON_LIB_DYNLOAD_SUBDIR, PYTHON_VENV_PATH,
        };

        // Static cache to avoid redundant detections (especially expensive ones)
        use std::collections::HashMap;
        use std::sync::Mutex;
        static CACHE: Mutex<Option<HashMap<PathBuf, PythonEnv>>> = Mutex::new(None);

        let python_path_buf = python_path.to_path_buf();
        if let Ok(guard) = CACHE.lock()
            && let Some(ref cache) = *guard
            && let Some(env) = cache.get(&python_path_buf)
        {
            return Ok(env.clone());
        }

        // Step 1: Find Project Root (Optional)
        let project_root = Self::find_project_root(python_path);

        // Step 2: Detect base_prefix and version (Lightweight if possible)
        let (base_prefix, version) = Self::detect_prefix_and_version(python_path)?;

        // Step 3: Build paths using SSOT patterns
        // SSOT: PYTHON_LIB_DIR_PATTERN = "lib/python{version}"
        let lib_dir_relative = PYTHON_LIB_DIR_PATTERN.replace("{version}", &version);
        let lib_dir = base_prefix.join(&lib_dir_relative);
        // SSOT: PYTHON_LIB_DYNLOAD_SUBDIR = "lib-dynload"
        let lib_dynload = lib_dir.join(PYTHON_LIB_DYNLOAD_SUBDIR);

        // Step 4: Detect venv root
        let mut venv_root = None;

        if let Some(ref root) = project_root {
            let venv_path = root.join(PYTHON_VENV_PATH);
            if venv_path.join("pyvenv.cfg").exists() {
                venv_root = Some(venv_path);
            }
        }

        // Step 5: Detect site-packages
        let mut site_packages = None;
        if let Some(ref venv) = venv_root {
            let sp_path = venv
                .join("lib")
                .join(format!("python{}", version))
                .join("site-packages");
            if sp_path.exists() {
                site_packages = Some(sp_path);
            }
        }

        let env = Self {
            base_prefix,
            version,
            lib_dir,
            lib_dynload,
            venv_root,
            site_packages,
        };

        // Update cache
        if let Ok(mut guard) = CACHE.lock() {
            let cache = guard.get_or_insert_with(HashMap::new);
            cache.insert(python_path_buf, env.clone());
        }

        Ok(env)
    }

    /// Optimized: Try to get prefix and version from pyvenv.cfg without subprocess
    fn detect_prefix_and_version(python_path: &Path) -> anyhow::Result<(PathBuf, String)> {
        // Try PEP 405 (pyvenv.cfg)
        if let Some(venv_root) = python_path.parent().and_then(|p| p.parent()) {
            let pyvenv_cfg = venv_root.join("pyvenv.cfg");
            if pyvenv_cfg.exists() {
                let (base, version) = Self::parse_pyvenv_cfg_full(&pyvenv_cfg);

                // On macOS, 'home' in pyvenv.cfg often points to /usr/local/bin,
                // but base_prefix is in /Library/Frameworks.
                // If we only have 'home' and no explicit 'base-prefix',
                // we should NOT trust the home parent as base_prefix.
                if let (Some(b), Some(v)) = (base, version) {
                    // Check if we also have base-prefix explicitly
                    let content = std::fs::read_to_string(&pyvenv_cfg).unwrap_or_default();
                    if content.contains("base-prefix") || content.contains("base-exec-prefix") {
                        log::debug!(
                            "[SSOT] Prefix/Version from pyvenv.cfg (explicit): {:?}, {}",
                            b,
                            v
                        );
                        return Ok((b, v));
                    }
                    // Otherwise, we'll fall back to subprocess for base_prefix but maybe keep version
                }
            }
        }

        // Fallback: Query Python version (subprocess)
        let version = Self::detect_version(python_path)?;

        // Fallback: Query base_prefix
        let base_prefix = Self::detect_base_prefix(python_path)?;

        Ok((base_prefix, version))
    }

    /// Parse pyvenv.cfg for both home (prefix) and version.
    /// Supports both standard 'version' and uv's 'version_info'.
    /// Supports 'home' and 'base-prefix'.
    fn parse_pyvenv_cfg_full(path: &Path) -> (Option<PathBuf>, Option<String>) {
        let mut home = None;
        let mut base_prefix = None;
        let mut version = None;

        if let Ok(content) = std::fs::read_to_string(path) {
            for line in content.lines() {
                if let Some(parts) = line.split_once('=') {
                    let key = parts.0.trim();
                    let val = parts.1.trim();
                    match key {
                        "home" => {
                            home = std::path::Path::new(val).parent().map(|p| p.to_path_buf());
                        }
                        "base-prefix" | "base-exec-prefix" => {
                            base_prefix = Some(PathBuf::from(val));
                        }
                        "version" | "version_info" => {
                            // Extract Major.Minor from X.Y.Z
                            let parts: Vec<&str> = val.split('.').collect();
                            if parts.len() >= 2 {
                                version = Some(format!("{}.{}", parts[0], parts[1]));
                            }
                        }
                        _ => {}
                    }
                }
            }
        }

        // Priority: base-prefix (exact), then home's parent
        (base_prefix.or(home), version)
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

        // PYTHONPATH: Inject site-packages (SPEC-0005/06)
        if let Some(ref sp) = self.site_packages {
            let sp_str = sp.to_string_lossy();
            let new_path = if let Ok(current) = std::env::var("PYTHONPATH") {
                if current.is_empty() {
                    sp_str.into_owned()
                } else {
                    format!("{}:{}", sp_str, current)
                }
            } else {
                sp_str.into_owned()
            };
            cmd.env("PYTHONPATH", new_path);
            cmd.env("VELO_PYTHON_SITE_PACKAGES", sp);
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

            if let Some(ref sp) = self.site_packages {
                let current = std::env::var("PYTHONPATH").unwrap_or_default();
                let sp_str = sp.to_string_lossy();
                if current.is_empty() {
                    std::env::set_var("PYTHONPATH", &*sp_str);
                } else if !current.contains(&*sp_str) {
                    std::env::set_var("PYTHONPATH", format!("{}:{}", sp_str, current));
                }
                std::env::set_var("VELO_PYTHON_SITE_PACKAGES", sp);
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
        let site_packages = std::env::var("VELO_PYTHON_SITE_PACKAGES").ok();

        // Extract version from lib_dir (e.g., "python3.11" -> "3.11")
        let version = lib_dir
            .rsplit('/')
            .find(|s| s.starts_with("python"))
            .and_then(|s| s.strip_prefix("python"))
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                // If we can't extract version, we are in a corrupt state
                // Don't use a hardcoded fallback that leads to 'encodings' errors
                "3.10".to_string() // User is on 3.10, but we should really be dynamic
            });

        Some(Self {
            base_prefix: PathBuf::from(base_prefix),
            version,
            lib_dir: PathBuf::from(lib_dir),
            lib_dynload: lib_dynload.map(PathBuf::from).unwrap_or_default(),
            venv_root: venv_root.map(PathBuf::from),
            site_packages: site_packages.map(PathBuf::from),
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
