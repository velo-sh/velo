//! Handle 'velo run' command
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::{Result, bail};
use clap::Parser;
use std::path::{Path, PathBuf};

use crate::cache::EnvCache;
use crate::config::VeloConfig;
use crate::python_info::{PythonInfo, PythonVersion};
use crate::zygote::ZygoteLauncher;
use crate::{python, runner};

/// Run a Python script
#[derive(Parser, Debug)]
#[command(name = "run", about = "Run a Python script")]
pub struct RunCmd {
    /// Python script to run
    #[arg(required = true)]
    pub script: String,

    /// Use Zygote for fast startup (auto-starts if needed)
    #[arg(long)]
    pub zygote: bool,

    /// Run script asynchronously in background (implies --zygote)
    #[arg(long = "async")]
    pub async_mode: bool,

    /// Show detailed startup timing breakdown
    #[arg(long)]
    pub profile: bool,

    /// Use fast loader with bundle acceleration
    #[arg(long)]
    pub fast: bool,
}

impl RunCmd {
    /// Validate arguments
    pub fn validate(&self) -> Result<()> {
        // Mutual exclusion check (Phase 5.1 / AUDIT-51-001)
        if self.async_mode && self.profile {
            bail!(
                "--async and --profile are mutually exclusive\n\
                 Profiling requires synchronous execution to capture full trace."
            );
        }
        Ok(())
    }

    /// Check if Zygote should be enabled (explicitly or via --async)
    pub fn zygote_enabled(&self) -> bool {
        self.zygote || self.async_mode
    }
}

/// Handle 'velo run' command (entry point from cli.rs)
pub fn cmd_run(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = RunCmd::try_parse_from(&args[1..])?;

    // Validate
    cmd.validate()?;

    // Run the script
    run_script_impl(&cmd)
}

/// Internal implementation of script running
#[allow(clippy::collapsible_if)]
fn run_script_impl(cmd: &RunCmd) -> Result<()> {
    let _total_start = std::time::Instant::now();
    let script_path = Path::new(&cmd.script);
    let mut project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // 1. Project discovery
    if let Some(parent) = script_path.parent() {
        let p = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };

        if p.join("pyproject.toml").exists() {
            project_dir = p.to_path_buf();
        } else if let Some(grandparent) = p.parent() {
            if grandparent.join("pyproject.toml").exists() {
                project_dir = grandparent.to_path_buf();
            }
        }
    }
    let _discovery_time = _total_start.elapsed();

    // 2. Load config
    let _config_start = std::time::Instant::now();
    let config = VeloConfig::from_path(&project_dir.join("pyproject.toml")).unwrap_or_default();
    let _config_time = _config_start.elapsed();

    // 3. Detect Python
    let _python_start = std::time::Instant::now();
    let python_path = python::detect_python(&project_dir)?;
    let _python_time = _python_start.elapsed();

    if cmd.profile {
        eprintln!(
            "[VELO] Discovery: {:.1}ms, Config: {:.1}ms, Python Detect: {:.1}ms",
            _discovery_time.as_secs_f64() * 1000.0,
            _config_time.as_secs_f64() * 1000.0,
            _python_time.as_secs_f64() * 1000.0
        );
    }

    // 4. Zygote/Fast/Normal run
    if cmd.zygote_enabled() {
        let _zygote_start = std::time::Instant::now();
        if let Some(()) = try_zygote_run(
            &python_path,
            &cmd.script,
            cmd.async_mode,
            cmd.fast,
            &project_dir,
            &config,
        )? {
            if cmd.profile {
                eprintln!(
                    "[VELO] Zygote Total: {:.1}ms, Total E2E: {:.1}ms",
                    _zygote_start.elapsed().as_secs_f64() * 1000.0,
                    _total_start.elapsed().as_secs_f64() * 1000.0
                );
            }
            return Ok(());
        }
    }

    // Normal mode (or fallback)
    let (pythonpath, needs_capture) = python::setup_python_env(&project_dir, &python_path);

    // Fast mode: inject sitecustomize to activate bundle loader
    if cmd.fast {
        run_with_fast_loader(
            &python_path,
            &cmd.script,
            &project_dir,
            pythonpath,
            config.max_bundle_size,
        )?;
    } else if cmd.profile {
        runner::run_script_with_profile(&python_path, &cmd.script, pythonpath)?;
    } else {
        runner::run_script(&python_path, &cmd.script, pythonpath)?;
    }

    // If we didn't have cache, capture sys.path for next time
    if needs_capture {
        save_cache_if_needed(&project_dir, &python_path);
    }

    Ok(())
}

/// Try to run via Zygote, returns Some(()) on success, None on failure
#[cfg(unix)]
fn try_zygote_run(
    python_path: &Path,
    script_path: &str,
    async_enabled: bool,
    fast_enabled: bool,
    project_dir: &Path,
    config: &VeloConfig,
) -> Result<Option<()>> {
    use crate::zygote;

    if !zygote::is_supported() {
        return Ok(None);
    }

    let socket_path = zygote::ipc::default_socket_path();
    let script = Path::new(script_path);

    // Check if Zygote is running, start if not (hybrid mode)
    let mut launcher =
        ZygoteLauncher::new(socket_path.clone()).with_python(python_path.to_path_buf());

    let started_new = if !socket_path.exists() {
        // Read preload config from pyproject.toml (DEV-FIX-001)
        let config = VeloConfig::from_pyproject_toml();
        let preload: Vec<&str> = config
            .as_ref()
            .map(|c| c.preload.iter().map(|s| s.as_str()).collect())
            .unwrap_or_default();

        if preload.is_empty() {
            eprintln!("🚀 Starting Zygote...");
        } else {
            eprintln!("🚀 Starting Zygote with preload: {:?}", preload);
        }

        if let Err(e) = launcher.start(&preload, None) {
            eprintln!("⚠️ Failed to start Zygote: {}", e);
            eprintln!("   Falling back to normal mode");
            return Ok(None);
        }
        eprintln!("✅ Zygote ready");
        true
    } else {
        false
    };

    // Try to spawn via Zygote
    // Try to spawn via Zygote
    if socket_path.exists() {
        let (bundle_path, max_size) = if fast_enabled {
            (
                find_bundle(project_dir, script_path),
                config.max_bundle_size,
            )
        } else {
            (None, None)
        };

        // RFC-0014: High-Reliability Spawn Loop (AUDIT-51-002)
        let mut retries = 3;
        let mut backoff_ms = 100;

        while retries > 0 {
            match launcher.spawn_worker(
                script,
                &[],
                async_enabled,
                fast_enabled,
                bundle_path.clone(),
                Some(project_dir.to_path_buf()),
                max_size,
            ) {
                Ok(worker) => {
                    if async_enabled {
                        eprintln!("⚡ Worker spawned in background (PID: {})", worker.pid());
                        if let Some(stdout) = worker.stdout_path() {
                            eprintln!("📝 Logs (stdout): {}", stdout.display());
                        }
                        if let Some(stderr) = worker.stderr_path() {
                            eprintln!("📝 Logs (stderr): {}", stderr.display());
                        }

                        // Keep Zygote alive but exit CLI immediately
                        if started_new {
                            std::mem::forget(launcher);
                        }
                        std::process::exit(0);
                    }

                    // Wait for worker to complete and get exit code
                    let exit_code = worker.wait().unwrap_or(1);

                    // Keep Zygote alive if we started it (daemon mode)
                    if started_new {
                        std::mem::forget(launcher);
                    }

                    // Exit with worker's exit code
                    std::process::exit(exit_code);
                }
                Err(e) => {
                    let err_msg = e.to_string();
                    let is_transient = err_msg.contains("Connection refused")
                        || err_msg.contains("Broken pipe")
                        || err_msg.contains("connection error")
                        || err_msg.contains("failed to fill whole buffer");

                    if is_transient && retries > 1 {
                        retries -= 1;
                        std::thread::sleep(std::time::Duration::from_millis(backoff_ms));
                        backoff_ms *= 2;
                        continue;
                    }

                    // Final fallback
                    eprintln!("⚠️ Zygote spawn failed: {}", e);
                    return Ok(None);
                }
            }
        }
    }

    Ok(None)
}

#[cfg(not(unix))]
fn try_zygote_run(
    _python_path: &Path,
    _script_path: &str,
    _async_enabled: bool,
) -> Result<Option<()>> {
    // Zygote not supported on non-Unix platforms
    Ok(None)
}

/// Save cache after script execution
fn save_cache_if_needed(project_dir: &Path, python_path: &Path) {
    // Detect Python info for ABI fingerprinting
    let python_info = match PythonInfo::detect(python_path) {
        Ok(info) => info,
        Err(_) => return, // Skip cache if detection fails
    };

    // Compute fingerprint
    let fingerprint = match EnvCache::compute_fingerprint(project_dir) {
        Some(fp) => fp,
        None => return, // No uv.lock, skip caching
    };

    // Capture sys.path
    match python::capture_sys_path(python_path) {
        Ok(syspath) => {
            let python_home = python_path
                .parent()
                .and_then(|p| p.parent())
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_default();

            let env_cache = EnvCache::new(
                fingerprint,
                syspath,
                python_home,
                PythonVersion {
                    major: python_info.version.major,
                    minor: python_info.version.minor,
                    patch: python_info.version.patch,
                },
                python_info.abi_tag.clone(),
                python_info.platform_tag.clone(),
            );

            // Save cache
            if let Err(e) = env_cache.save(project_dir) {
                eprintln!("Warning: failed to save cache: {}", e);
            }
        }
        Err(e) => {
            eprintln!("Warning: failed to capture sys.path: {}", e);
        }
    }
}

fn find_bundle(project_dir: &Path, script_path: &str) -> Option<PathBuf> {
    let script_dir = Path::new(script_path).parent().unwrap_or(Path::new("."));
    let possible_bundles = [
        project_dir.join(".velo/cache/bundle.veloc"),
        project_dir.join("bundle.veloc"),
        script_dir.join("bundle.veloc"),
    ];

    possible_bundles.iter().find(|p| p.exists()).cloned()
}

/// Run script with fast loader (bundle-accelerated imports)
///
/// RFC-0006: Injects sitecustomize.py to activate VeloBundle import hook
fn run_with_fast_loader(
    python_path: &Path,
    script_path: &str,
    project_dir: &Path,
    pythonpath: Option<String>,
    max_bundle_size: Option<u64>,
) -> Result<()> {
    use std::io::Write;

    let res = (|| -> Result<()> {
        // Find bundle.veloc - check multiple locations
        let actual_bundle = match find_bundle(project_dir, script_path) {
            Some(p) => p,
            None => {
                eprintln!("⚠️  No bundle found. Build one first:");
                eprintln!("    python python/bundle_builder.py .");
                eprintln!("   Falling back to normal mode...");
                return runner::run_script(python_path, script_path, pythonpath);
            }
        };

        // RFC-0008: Mandatory Security Pre-validation (H-1, H-2, H-4, H-5)
        // This provides a structural lock at the Rust boundary.
        if let Err(e) = crate::loader::verify::load_and_verify(&actual_bundle, max_bundle_size) {
            eprintln!("⚠️  Fast loader security check failed: {}", e);
            eprintln!("   Falling back to normal imports...");
            return runner::run_script(python_path, script_path, pythonpath);
        }

        eprintln!("⚡ Fast mode: loading from {}", actual_bundle.display());

        let bundle_abs = actual_bundle.canonicalize()?;
        let project_abs = project_dir.canonicalize()?;

        // Create a unique temporary directory for sitecustomize.py
        // RFC-0006: Injects sitecustomize.py to activate VeloBundle import hook
        let temp_dir = tempfile::tempdir()?;
        let site_file = temp_dir.path().join("sitecustomize.py");

        // Get absolute paths

        // Find velo_loader.py - check multiple locations
        let exe_path = std::env::current_exe()?;
        let possible_paths = [
            // 1. Project directory (development)
            project_abs.join("python"),
            // 2. Source workspace (cargo run from workspace)
            exe_path
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .join("python"),
            // 3. Next to executable (installed)
            exe_path.parent().unwrap().join("python"),
            // 4. Installed in share (system install)
            exe_path
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .join("share/velo/python"),
        ];

        let velo_loader_path = possible_paths
            .iter()
            .find(|p: &&PathBuf| p.join("velo_loader.py").exists())
            .cloned()
            .unwrap_or_else(|| possible_paths[0].clone());

        // Write sitecustomize content
        let mut f = std::fs::File::create(&site_file)?;
        writeln!(
            f,
            r#"# Velo Fast Loader sitecustomize
import sys
sys.path.insert(0, r"{velo_loader}")

try:
    from velo_loader import activate_fast_mode
    from pathlib import Path
    
    bundle_path = Path(r"{bundle}")
    project_root = Path(r"{project}")
    max_size = {max_size}
    
    _bundle = activate_fast_mode(bundle_path, project_root, max_size)
    print("⚡ Fast loader active:", len(_bundle), "modules")
except Exception as e:
    print(f"⚠️  Fast loader failed: {{e}}")
    print("   Falling back to normal imports...")
"#,
            velo_loader = velo_loader_path.display(),
            bundle = bundle_abs.display(),
            project = project_abs.display(),
            max_size = max_bundle_size
                .map(|s| s.to_string())
                .unwrap_or_else(|| "None".to_string()),
        )?;
        f.flush()?;

        // Add site dir to PYTHONPATH
        let site_dir_str = temp_dir.path().to_string_lossy().to_string();
        let enhanced_pythonpath = match pythonpath {
            Some(p) if !p.is_empty() => format!("{}:{}", p, site_dir_str),
            _ => site_dir_str,
        };

        // Run script with enhanced PYTHONPATH
        // Cleanup: temp_dir will be automatically deleted when goes out of scope
        runner::run_script(python_path, script_path, Some(enhanced_pythonpath))
    })();

    // Always report metrics, even on error
    crate::graph::report_metrics();
    res
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use tempfile::tempdir;

    // ========================================================================
    // RunCmd clap parsing tests
    // ========================================================================

    #[test]
    fn test_parse_basic() {
        let cmd = RunCmd::try_parse_from(["run", "script.py"]).unwrap();
        assert_eq!(cmd.script, "script.py");
        assert!(!cmd.zygote);
        assert!(!cmd.async_mode);
        assert!(!cmd.profile);
        assert!(!cmd.fast);
    }

    #[test]
    fn test_parse_with_zygote() {
        let cmd = RunCmd::try_parse_from(["run", "--zygote", "script.py"]).unwrap();
        assert!(cmd.zygote);
        assert!(cmd.zygote_enabled());
    }

    #[test]
    fn test_parse_with_async() {
        let cmd = RunCmd::try_parse_from(["run", "--async", "script.py"]).unwrap();
        assert!(cmd.async_mode);
        assert!(cmd.zygote_enabled()); // --async implies zygote
    }

    #[test]
    fn test_parse_with_profile() {
        let cmd = RunCmd::try_parse_from(["run", "--profile", "script.py"]).unwrap();
        assert!(cmd.profile);
    }

    #[test]
    fn test_parse_with_fast() {
        let cmd = RunCmd::try_parse_from(["run", "--fast", "script.py"]).unwrap();
        assert!(cmd.fast);
    }

    #[test]
    fn test_validate_async_profile_mutual_exclusion() {
        let cmd = RunCmd::try_parse_from(["run", "--async", "--profile", "script.py"]).unwrap();
        let result = cmd.validate();
        assert!(result.is_err());
        assert!(
            result
                .unwrap_err()
                .to_string()
                .contains("mutually exclusive")
        );
    }

    #[test]
    fn test_missing_script_error() {
        let result = RunCmd::try_parse_from(["run"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_unknown_option_error() {
        let result = RunCmd::try_parse_from(["run", "--unknown", "script.py"]);
        assert!(result.is_err());
    }

    // ========================================================================
    // Project directory detection test
    // ========================================================================

    #[test]
    fn test_project_dir_detection_relative_path() -> Result<()> {
        let temp = tempdir()?;
        let project_root = temp.path();

        // Create pyproject.toml in temp dir
        File::create(project_root.join("pyproject.toml"))?;

        // Scenario: Script is "main.py" and we are in the same directory
        let script_path = Path::new("main.py");
        let parent = script_path.parent().unwrap();
        assert_eq!(parent.as_os_str(), "");

        // The logic from run_script_impl:
        let p = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };

        // Verify we can find pyproject.toml using this path
        let found = project_root.join(p).join("pyproject.toml").exists();
        assert!(
            found,
            "Should find pyproject.toml even with empty parent path"
        );

        // Verify canonicalize works on the fixed path
        let abs_path = project_root.join(p).canonicalize()?;
        assert!(abs_path.is_absolute());

        Ok(())
    }
}
