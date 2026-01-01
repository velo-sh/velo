use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

use velo::cache::{self, EnvCache};
use velo::zygote::{self, ZygoteLauncher};
use velo::{hardware, profile, python_info};

const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run [OPTIONS] <script.py>
    velo zygote <start|stop|status>
    velo info

COMMANDS:
    run      Run a Python script
    zygote   Manage Zygote pre-warming daemon
    info     Show environment information

RUN OPTIONS:
    --zygote   Use Zygote for fast startup (auto-starts if needed)
    --profile  Show detailed startup timing breakdown

OPTIONS:
    -h, --help     Print help
    -V, --version  Print version
";

/// Detect the project's Python interpreter.
/// Priority:
/// 1. .venv/bin/python (uv/virtualenv)
/// 2. VELO_PYTHON environment variable
/// 3. System python3
fn detect_python(project_dir: &Path) -> Result<std::path::PathBuf> {
    // 1. Check for .venv/bin/python
    let venv_python = project_dir.join(".venv/bin/python");
    if venv_python.exists() {
        return Ok(venv_python);
    }

    // 2. Check VELO_PYTHON env var
    if let Ok(python) = std::env::var("VELO_PYTHON") {
        let path = std::path::PathBuf::from(&python);
        if path.exists() {
            return Ok(path);
        }
    }

    // 3. Fall back to system python3
    // First check if python3 exists in PATH
    if let Ok(output) = Command::new("which").arg("python3").output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            return Ok(std::path::PathBuf::from(path));
        }
    }

    anyhow::bail!("No Python interpreter found. Please create a .venv or set VELO_PYTHON")
}

/// Detect .venv/lib/python*/site-packages
fn detect_venv_site_packages(project_dir: &Path) -> Option<String> {
    let venv_lib = project_dir.join(".venv/lib");
    if !venv_lib.exists() {
        return None;
    }

    if let Ok(entries) = std::fs::read_dir(&venv_lib) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if name_str.starts_with("python3") {
                let site_packages = entry.path().join("site-packages");
                if site_packages.exists() {
                    return Some(site_packages.to_string_lossy().to_string());
                }
            }
        }
    }

    None
}

/// Capture sys.path from Python and cache it.
fn capture_sys_path(python: &Path) -> Result<Vec<String>> {
    let output = Command::new(python)
        .args(["-c", "import sys; print('\\n'.join(sys.path))"])
        .output()
        .context("Failed to run Python to capture sys.path")?;

    if !output.status.success() {
        anyhow::bail!("Python failed to report sys.path");
    }

    let paths: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(paths)
}

/// Setup Python environment, potentially using cache.
/// Returns (pythonpath, needs_capture) - if needs_capture is true, caller should
/// capture sys.path after script runs for next time.
fn setup_python_env(project_dir: &Path, _python: &Path) -> (Option<String>, bool) {
    // Auto-detect venv site-packages
    let venv_site_packages = detect_venv_site_packages(project_dir);

    // Try to load cache if fingerprint matches
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Some(cache) = EnvCache::load(project_dir, &fingerprint) {
            // Check cache version compatibility
            if !cache.is_version_compatible() {
                eprintln!(
                    "⚠️  Cache version mismatch\n\
                     ├─ Cached:  v{}\n\
                     └─ Current: v{}\n\
                     Rebuilding cache...\n",
                    cache.cache_version,
                    cache::CACHE_VERSION
                );
                return (venv_site_packages, true);
            }

            // Check if cache has ABI info (Phase 1.5+)
            // If abi_tag is empty, this is old cache format - rebuild
            if cache.abi_tag.is_empty() {
                eprintln!("⚠️  Cache missing ABI info, rebuilding...\n");
                return (venv_site_packages, true);
            }

            // Fast path: compare Python executable path hash instead of spawning Python
            // The ABI is stable for a given Python binary, so if fingerprint matches
            // and cache has ABI, we trust it without re-detecting
            // (fingerprint includes uv.lock which tracks Python version)

            let mut paths = cache.sys_path.clone();

            // Prepend venv site-packages if detected
            if let Some(ref venv_path) = venv_site_packages {
                if !paths.contains(venv_path) {
                    paths.insert(0, venv_path.clone());
                }
            }

            return (Some(paths.join(":")), false);
        }
    }

    // No cache - just use venv site-packages for now, capture later
    (venv_site_packages, true)
}

fn run_script(python: &Path, script_path: &str, pythonpath: Option<String>) -> Result<()> {
    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Get script directory for relative imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}", script_dir, pp),
        None => script_dir,
    };

    // Run the script using user's Python
    let status = Command::new(python)
        .env("PYTHONPATH", &final_pythonpath)
        .env("PYTHONUNBUFFERED", "1")
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

/// Run a Python script with profiling enabled.
/// Injects sitecustomize.py to track import times and displays results.
fn run_script_with_profile(
    python: &Path,
    script_path: &str,
    pythonpath: Option<String>,
) -> Result<()> {
    use std::fs;
    use std::io::Write;

    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Create temp directory for sitecustomize.py and profile output
    let temp_dir = std::env::temp_dir().join("velo_profile");
    fs::create_dir_all(&temp_dir)?;

    // Write sitecustomize.py
    let sitecustomize_path = temp_dir.join("sitecustomize.py");
    let mut file = fs::File::create(&sitecustomize_path)?;
    file.write_all(profile::SITECUSTOMIZE_PY.as_bytes())?;

    // Profile output path
    let profile_output = temp_dir.join("profile.json");

    // Get script directory for relative imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH with temp dir first (for sitecustomize.py)
    let temp_dir_str = temp_dir.to_string_lossy().to_string();
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}:{}", temp_dir_str, script_dir, pp),
        None => format!("{}:{}", temp_dir_str, script_dir),
    };

    println!("⏱️  Running with profiling enabled...\n");

    // Measure total time
    let start = std::time::Instant::now();

    // Run the script using user's Python with profile output env var
    let status = Command::new(python)
        .env("PYTHONPATH", &final_pythonpath)
        .env("PYTHONUNBUFFERED", "1")
        .env("VELO_PROFILE_OUTPUT", &profile_output)
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;

    let total_time = start.elapsed();

    // Display profile results if available
    if profile_output.exists() {
        if let Ok(profile_data) = profile::ProfileData::from_file(&profile_output) {
            println!("\n{}", profile_data.format_table(10));

            // Show optimization suggestions for top imports
            let top = profile_data.top_imports(5);
            let suggestions: Vec<_> = top
                .iter()
                .filter_map(|(name, _)| {
                    profile::get_optimization_suggestions(name)
                        .map(|s| format!("   • {}: {}", name, s))
                })
                .collect();

            if !suggestions.is_empty() {
                println!("💡 Optimization Suggestions:");
                for s in suggestions {
                    println!("{}", s);
                }
                println!();
            }
        }
    }

    println!("Total execution time: {:.2}s", total_time.as_secs_f64());

    // Cleanup temp files
    let _ = fs::remove_file(&sitecustomize_path);
    let _ = fs::remove_file(&profile_output);

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    if args.len() < 2 {
        print!("{}", USAGE);
        std::process::exit(0);
    }

    match args[1].as_str() {
        "-h" | "--help" => {
            print!("{}", USAGE);
            std::process::exit(0);
        }
        "-V" | "--version" => {
            println!("velo {}", env!("CARGO_PKG_VERSION"));
            std::process::exit(0);
        }
        "run" => {
            if args.len() < 3 {
                eprintln!("Error: missing script path");
                eprintln!("Usage: velo run [--zygote] [--profile] <script.py>");
                std::process::exit(1);
            }

            // Parse flags
            let mut zygote_enabled = false;
            let mut profile_enabled = false;
            let mut script_arg_idx = 2;

            for (i, arg) in args.iter().enumerate().skip(2) {
                match arg.as_str() {
                    "--zygote" => {
                        zygote_enabled = true;
                        script_arg_idx = i + 1;
                    }
                    "--profile" => {
                        profile_enabled = true;
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
                eprintln!("Usage: velo run [--zygote] [--profile] <script.py>");
                std::process::exit(1);
            }

            // Determine project directory
            let project_dir =
                std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

            // Detect user's Python
            let python = detect_python(&project_dir)?;

            // Zygote mode: use pre-warmed process
            if zygote_enabled {
                #[cfg(unix)]
                {
                    if !zygote::is_supported() {
                        eprintln!("⚠️ Zygote not supported on this platform, using normal mode");
                    } else {
                        let socket_path = zygote::ipc::default_socket_path();
                        let script_path = Path::new(&args[script_arg_idx]);

                        // Check if Zygote is running, start if not (hybrid mode)
                        let mut launcher =
                            ZygoteLauncher::new(socket_path.clone()).with_python(python.clone());

                        if !socket_path.exists() {
                            eprintln!("🚀 Starting Zygote...");
                            if let Err(e) = launcher.start(&[]) {
                                eprintln!("⚠️ Failed to start Zygote: {}", e);
                                eprintln!("   Falling back to normal mode");
                            } else {
                                eprintln!("✅ Zygote ready");
                            }
                        }

                        // Try to spawn via Zygote
                        if socket_path.exists() {
                            match launcher.spawn_worker(script_path, &[]) {
                                Ok(worker) => {
                                    // Wait for worker (polling for now)
                                    eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());
                                    // Worker runs independently, we exit
                                    return Ok(());
                                }
                                Err(e) => {
                                    eprintln!("⚠️ Zygote spawn failed: {}", e);
                                    eprintln!("   Falling back to normal mode");
                                }
                            }
                        }
                    }
                }
                #[cfg(not(unix))]
                {
                    eprintln!("⚠️ Zygote not supported on Windows, using normal mode");
                }
            }

            // Normal mode (or fallback)
            let (pythonpath, needs_capture) = setup_python_env(&project_dir, &python);

            if profile_enabled {
                run_script_with_profile(&python, &args[script_arg_idx], pythonpath)?;
            } else {
                run_script(&python, &args[script_arg_idx], pythonpath)?;
            }

            // If we didn't have cache, capture sys.path for next time
            if needs_capture {
                if let Some(fingerprint) = EnvCache::compute_fingerprint(&project_dir) {
                    if let Ok(paths) = capture_sys_path(&python) {
                        let (python_version, abi_tag, platform_tag) =
                            match python_info::PythonInfo::detect(&python) {
                                Ok(info) => (info.version, info.abi_tag, info.platform_tag),
                                Err(_) => (
                                    python_info::PythonVersion::default(),
                                    String::new(),
                                    String::new(),
                                ),
                            };

                        let cache = EnvCache::new(
                            fingerprint,
                            paths,
                            String::new(),
                            python_version,
                            abi_tag,
                            platform_tag,
                        );
                        let _ = cache.save(&project_dir);
                    }
                }
            }
        }
        "info" => {
            // Determine project directory
            let project_dir =
                std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

            println!("Velo {}", env!("CARGO_PKG_VERSION"));
            println!("══════════════════════════════════════════════════════════════\n");

            // Hardware info
            let hw_info = hardware::HardwareInfo::detect();
            println!("{}\n", hw_info.format());

            // Python environment
            if let Ok(python) = detect_python(&project_dir) {
                println!("▸ Python Environment");
                println!("├─ Path:    {}", python.display());
                if let Ok(info) = python_info::PythonInfo::detect(&python) {
                    println!("├─ Version: {}", info.version);
                    println!("├─ ABI:     {}-{}", info.abi_tag, info.platform_tag);
                }
                println!();
            } else {
                println!("▸ Python Environment");
                println!("└─ Not detected (no .venv or VELO_PYTHON set)\n");
            }

            // Cache status
            println!("▸ Cache Status");
            let cache_dir = cache::EnvCache::cache_dir(&project_dir);
            if cache_dir.exists() {
                if let Some(fingerprint) = EnvCache::compute_fingerprint(&project_dir) {
                    if let Some(cache) = EnvCache::load(&project_dir, &fingerprint) {
                        println!("├─ Location:    {}", cache_dir.display());
                        println!("├─ Fingerprint: {}...", &fingerprint[..16]);
                        println!(
                            "├─ Python:      {} ({})",
                            cache.python_version, cache.abi_tag
                        );
                        println!("├─ Version:     v{}", cache.cache_version);
                        println!("└─ Status:      Valid ✅");
                    } else {
                        println!("├─ Location:    {}", cache_dir.display());
                        println!("└─ Status:      Stale (fingerprint mismatch) ⚠️");
                    }
                } else {
                    println!("├─ Location:    {}", cache_dir.display());
                    println!("└─ Status:      No uv.lock found");
                }
            } else {
                println!("└─ No cache (run a script first)");
            }
        }
        "zygote" => {
            if args.len() < 3 {
                eprintln!("Usage: velo zygote <start|stop|status>");
                std::process::exit(1);
            }

            let project_dir =
                std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

            match args[2].as_str() {
                "start" => {
                    #[cfg(unix)]
                    {
                        let python = detect_python(&project_dir)?;
                        let socket_path = zygote::ipc::default_socket_path();

                        if socket_path.exists() {
                            println!("⚡ Zygote already running");
                            println!("   Socket: {}", socket_path.display());
                        } else {
                            let mut launcher =
                                ZygoteLauncher::new(socket_path.clone()).with_python(python);

                            // Parse --preload if provided
                            let preload: Vec<&str> = if args.len() > 4 && args[3] == "--preload" {
                                args[4].split(',').collect()
                            } else {
                                vec![]
                            };

                            println!("🚀 Starting Zygote daemon...");
                            match launcher.start(&preload) {
                                Ok(()) => {
                                    println!("✅ Zygote started");
                                    println!("   Socket: {}", socket_path.display());
                                    // Keep launcher alive by forgetting it (daemon mode)
                                    std::mem::forget(launcher);
                                }
                                Err(e) => {
                                    eprintln!("❌ Failed to start Zygote: {}", e);
                                    std::process::exit(1);
                                }
                            }
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        eprintln!("❌ Zygote not supported on this platform");
                        std::process::exit(1);
                    }
                }
                "stop" => {
                    #[cfg(unix)]
                    {
                        let socket_path = zygote::ipc::default_socket_path();

                        if !socket_path.exists() {
                            println!("ℹ️  Zygote not running");
                        } else {
                            println!("🛑 Stopping Zygote...");
                            match zygote::ipc::send_command(
                                &socket_path,
                                zygote::ipc::ZygoteCommand::Shutdown,
                            ) {
                                Ok(_) => {
                                    println!("✅ Zygote stopped");
                                }
                                Err(e) => {
                                    eprintln!("⚠️  Error stopping Zygote: {}", e);
                                    // Force cleanup
                                    zygote::ipc::cleanup_socket(&socket_path);
                                    println!("   Socket cleaned up");
                                }
                            }
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        eprintln!("ℹ️  Zygote not supported on this platform");
                    }
                }
                "status" => {
                    #[cfg(unix)]
                    {
                        let socket_path = zygote::ipc::default_socket_path();

                        println!("▸ Zygote Status");
                        if socket_path.exists() {
                            println!("├─ Status: Running ✅");
                            println!("└─ Socket: {}", socket_path.display());
                        } else {
                            println!("└─ Status: Not running");
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        println!("▸ Zygote Status");
                        println!("└─ Not supported on this platform");
                    }
                }
                subcmd => {
                    eprintln!("Error: unknown zygote subcommand '{}'", subcmd);
                    eprintln!("Usage: velo zygote <start|stop|status>");
                    std::process::exit(1);
                }
            }
        }
        cmd => {
            eprintln!("Error: unknown command '{}'", cmd);
            eprintln!("{}", USAGE);
            std::process::exit(1);
        }
    }

    Ok(())
}
