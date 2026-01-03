//! Handle 'velo run' command

use anyhow::Result;
use std::path::{Path, PathBuf};

use crate::cache::EnvCache;
use crate::config::VeloConfig;
use crate::python_info::{PythonInfo, PythonVersion};
use crate::zygote::ZygoteLauncher;
use crate::{python, runner};

/// Handle 'velo run' command
#[allow(clippy::collapsible_if)]
pub fn cmd_run(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Error: missing script path");
        eprintln!("Usage: velo run [--zygote] [--profile] [--fast] <script.py>");
        std::process::exit(1);
    }

    // Parse flags
    let mut zygote_enabled = false;
    let mut async_enabled = false;
    let mut profile_enabled = false;
    let mut fast_enabled = false;
    let mut script_arg_idx = 2;

    for (i, arg) in args.iter().enumerate().skip(2) {
        match arg.as_str() {
            "--zygote" => {
                zygote_enabled = true;
                script_arg_idx = i + 1;
            }
            "--async" => {
                async_enabled = true;
                zygote_enabled = true;
                script_arg_idx = i + 1;
            }
            "--profile" => {
                profile_enabled = true;
                script_arg_idx = i + 1;
            }
            "--fast" => {
                fast_enabled = true;
                script_arg_idx = i + 1;
            }
            a if a.starts_with('-') => {
                eprintln!("Error: unknown option '{}'", a);
                std::process::exit(1);
            }
            _ => {
                script_arg_idx = i;
                break;
            }
        }
    }

    if script_arg_idx >= args.len() {
        eprintln!("Error: missing script path");
        eprintln!("Usage: velo run [--zygote] [--profile] [--fast] [--async] <script.py>");
        std::process::exit(1);
    }

    // Mutual exclusion check (Phase 5.1 / AUDIT-51-001)
    if async_enabled && profile_enabled {
        eprintln!("Error: --async and --profile are mutually exclusive");
        eprintln!("Profiling requires synchronous execution to capture full trace.");
        std::process::exit(1);
    }

    // Determine project directory by looking for pyproject.toml starting from script's parent
    let script_path = Path::new(&args[script_arg_idx]);
    let mut project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

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

    // Load config from discovered project root
    let config = VeloConfig::from_path(&project_dir.join("pyproject.toml")).unwrap_or_default();

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Zygote mode: use pre-warmed process
    if zygote_enabled {
        if let Some(()) = try_zygote_run(
            &python_path,
            &args[script_arg_idx],
            async_enabled,
            fast_enabled,
            &project_dir,
            &config,
        )? {
            return Ok(());
        }
        // Fallback to normal mode if Zygote fails
    }

    // Normal mode (or fallback)
    let (pythonpath, needs_capture) = python::setup_python_env(&project_dir, &python_path);

    // Fast mode: inject sitecustomize to activate bundle loader
    if fast_enabled {
        run_with_fast_loader(
            &python_path,
            &args[script_arg_idx],
            &project_dir,
            pythonpath,
            config.max_bundle_size,
        )?;
    } else if profile_enabled {
        runner::run_script_with_profile(&python_path, &args[script_arg_idx], pythonpath)?;
    } else {
        runner::run_script(&python_path, &args[script_arg_idx], pythonpath)?;
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

        if let Err(e) = launcher.start(&preload) {
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
    if socket_path.exists() {
        let (bundle_path, max_size) = if fast_enabled {
            (
                find_bundle(project_dir, script_path),
                config.max_bundle_size,
            )
        } else {
            (None, None)
        };

        match launcher.spawn_worker(
            script,
            &[],
            async_enabled,
            fast_enabled,
            bundle_path,
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

                // Exit with worker's exit code (DEF-P3-013/014)
                std::process::exit(exit_code);
            }
            Err(e) => {
                // Check if this is a stale socket (connection refused)
                let is_stale = e.to_string().contains("Connection refused")
                    || e.to_string().contains("Connection failed");

                if is_stale && !started_new {
                    // Stale socket - remove and restart Zygote
                    eprintln!("🔄 Stale socket detected, restarting Zygote...");
                    zygote::ipc::cleanup_socket(&socket_path);

                    if let Ok(()) = launcher.start(&[]) {
                        eprintln!("✅ Zygote ready");

                        // Retry spawn
                        let (bundle_path, max_size) = if fast_enabled {
                            (
                                find_bundle(project_dir, script_path),
                                config.max_bundle_size,
                            )
                        } else {
                            (None, None)
                        };

                        if let Ok(worker) = launcher.spawn_worker(
                            script,
                            &[],
                            async_enabled,
                            fast_enabled,
                            bundle_path,
                            Some(project_dir.to_path_buf()),
                            max_size,
                        ) {
                            if async_enabled {
                                eprintln!(
                                    "⚡ Worker spawned in background (PID: {})",
                                    worker.pid()
                                );
                                if let Some(stdout) = worker.stdout_path() {
                                    eprintln!("📝 Logs (stdout): {}", stdout.display());
                                }
                                if let Some(stderr) = worker.stderr_path() {
                                    eprintln!("📝 Logs (stderr): {}", stderr.display());
                                }
                                std::mem::forget(launcher);
                                return Ok(Some(()));
                            }

                            eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());
                            let exit_code = worker.wait().unwrap_or(1);
                            std::mem::forget(launcher);
                            std::process::exit(exit_code);
                        }
                    }
                }

                eprintln!("⚠️ Zygote spawn failed: {}", e);
                eprintln!("   Falling back to normal mode");
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

        // The logic from cmd_run:
        let p = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };

        // Verify we can find pyproject.toml using this path
        // (Simulating the check in cmd_run)
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
