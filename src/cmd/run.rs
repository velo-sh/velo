//! Handle 'velo run' command
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::{Result, bail};
use clap::Parser;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::cache::EnvCache;
use crate::common::diagnostics::{MarkdownFormatter, StartupTimeline};
pub use crate::common::paths::*;
use crate::config::VeloConfig;
use crate::custody::{AutopilotDecision, AutopilotEngine, EnvironmentSync};
use crate::python;
use crate::python_info::{PythonInfo, PythonVersion};
use crate::runner;
use crate::shm::registry::MemoryRegistry;
use crate::zygote::ZygoteLauncher;

/// Run a Python script or module
#[derive(Parser, Debug)]
#[command(name = "run", about = "Run a Python script or module")]
pub struct RunCmd {
    /// Python script to run (optional if -m is specified)
    #[arg(required_unless_present = "module")]
    pub script: Option<String>,

    /// Run a Python module as a script (like python -m) [RFC-0030]
    #[arg(short = 'm', long = "module", value_name = "MODULE")]
    pub module: Option<String>,

    /// Use Zygote for fast startup (auto-starts if needed)
    #[arg(long)]
    pub zygote: bool,

    /// Run script asynchronously in background (implies --zygote)
    #[arg(long = "async")]
    pub async_mode: bool,

    /// Show detailed startup timing breakdown
    #[arg(long)]
    pub profile: bool,

    /// Output AI-Native diagnostic report (RFC-0038)
    #[arg(long = "prof-md", value_name = "FILE")]
    pub prof_md: Option<PathBuf>,

    /// Output AI-Native diagnostic report as JSON (RFC-0038)
    #[arg(long = "prof-json", value_name = "FILE")]
    pub prof_json: Option<PathBuf>,

    /// Use fast loader with bundle acceleration
    #[arg(long)]
    pub fast: bool,

    /// Map a .safetensors file into shared memory (Memory Gravity)
    #[arg(long, value_name = "PATH")]
    pub shm: Option<PathBuf>,

    /// Enable Vibe Coding mode (real-time hot reload) [RFC-0029]
    #[arg(long)]
    pub vibe: bool,

    /// Alias for --vibe
    #[arg(long)]
    pub live: bool,

    /// Vibe gateway port (default: 8080 or VELO_VIBE_PORT)
    #[arg(long, default_value = "8080")]
    pub port: String,

    /// Additional arguments passed to the script/module [RFC-0030]
    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    pub args: Vec<String>,
}

impl RunCmd {
    /// Validate arguments
    pub fn validate(&self) -> Result<()> {
        // Mutual exclusion check (Phase 5.1 / AUDIT-51-001)
        let profiling_requested =
            self.profile || self.prof_md.is_some() || self.prof_json.is_some();
        if (self.async_mode || self.zygote) && profiling_requested {
            bail!(
                "Zygote/Async and Profiling (--profile, --prof-md, or --prof-json) are mutually exclusive\n\
                 Profiling requires synchronous native execution to capture full trace."
            );
        }
        // RFC-0030: Vibe mode requires a script (not module)
        if self.vibe_enabled() && self.script.is_none() {
            bail!("Vibe mode requires a script path, not a module (-m)");
        }
        Ok(())
    }

    /// Check if Zygote should be enabled (explicitly, via --async, or for --shm)
    pub fn zygote_enabled(&self) -> bool {
        self.zygote || self.async_mode || self.shm.is_some()
    }

    /// Check if Vibe mode is enabled (--vibe or --live)
    pub fn vibe_enabled(&self) -> bool {
        self.vibe || self.live
    }

    /// Check if running a module (-m) instead of a script
    pub fn is_module_mode(&self) -> bool {
        self.module.is_some()
    }

    /// Get the target (script path or module name)
    pub fn get_target(&self) -> &str {
        self.script
            .as_deref()
            .or(self.module.as_deref())
            .unwrap_or("")
    }
}

/// Handle 'velo run' command (entry point from cli.rs)
pub fn cmd_run(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = RunCmd::try_parse_from(&args[1..])?;

    // Validate
    cmd.validate()?;

    // RFC-0029/GAP-001: Vibe mode takes precedence
    if cmd.vibe_enabled() {
        return run_vibe_mode(&cmd);
    }

    // Run the script
    run_script_impl(&cmd)
}

/// Run in Vibe Coding mode (RFC-0029 / GAP-001)
///
/// This function delegates to the VibeEngine for real-time hot reload.
#[tokio::main]
async fn run_vibe_mode(cmd: &RunCmd) -> Result<()> {
    use crate::v_live::engine::VibeEngine;
    use colored::Colorize;

    // Determine port: CLI arg > Env Var > Default
    let port = if let Ok(env_port) = std::env::var("VELO_VIBE_PORT") {
        if !env_port.is_empty() {
            env_port
        } else {
            cmd.port.clone()
        }
    } else {
        cmd.port.clone()
    };

    let gateway_addr = format!("127.0.0.1:{}", port);
    // Script is guaranteed by validate()
    let target = PathBuf::from(cmd.script.as_ref().unwrap());

    println!("{}", "🏛️  Vibe Engine Activated".green().bold());
    println!("Architecture Directive: Phase 8 (Vibe-Coding)");

    let engine = VibeEngine::new(target, &gateway_addr);
    engine.start().await?;

    Ok(())
}

/// Internal implementation of script running
#[allow(clippy::collapsible_if)]
fn run_script_impl(cmd: &RunCmd) -> Result<()> {
    // RFC-0030: Module mode (-m) dispatch
    if cmd.is_module_mode() {
        return run_module_impl(cmd);
    }

    let _total_start = std::time::Instant::now();
    let script_path_str = cmd.script.as_ref().unwrap(); // guaranteed by clap validation
    let script_path = Path::new(script_path_str);
    let mut project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // 1. Project discovery
    if let Some(parent) = script_path.parent() {
        let p = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };

        if VeloPaths::pyproject(p).exists() {
            project_dir = p.to_path_buf();
        } else if let Some(grandparent) = p.parent() {
            if VeloPaths::pyproject(grandparent).exists() {
                project_dir = grandparent.to_path_buf();
            }
        }
    }
    let _discovery_time = _total_start.elapsed();

    // 2. Load config
    let _config_start = std::time::Instant::now();
    // Load config from discovered project root (with Env Var overrides)
    let config = VeloConfig::load_with_overrides(&VeloPaths::pyproject(&project_dir));
    let _config_time = _config_start.elapsed();

    // 3. Detect Python
    let _python_start = std::time::Instant::now();
    let python_path = python::detect_python(&project_dir)?;
    let _python_time = _python_start.elapsed();

    // 3.1 RFC-0035: Auto-Preload (Native Library Preload)
    // For non-Zygote runs, we do NOT load in the Rust process (SPEC-0007 alignment).
    // We only verify the existence/validity of the lock here; inheritance is handled in runner.rs.
    let lock_path = project_dir.join("preload.lock");
    if lock_path.exists() {
        use crate::custody::native_fingerprint::PreloadLock;
        if let Ok(json) = std::fs::read_to_string(&lock_path) {
            if let Err(e) = PreloadLock::from_json(&json) {
                tracing::warn!("Failed to parse preload.lock: {}", e);
            }
        }
    }

    if cmd.profile {
        eprintln!(
            "[VELO] Discovery: {:.1}ms, Config: {:.1}ms, Python Detect: {:.1}ms",
            _discovery_time.as_secs_f64() * 1000.0,
            _config_time.as_secs_f64() * 1000.0,
            _python_time.as_secs_f64() * 1000.0
        );
    }

    // 3.5 RFC-0018: Environment Sync (ensure deps are up-to-date)
    let env_sync = EnvironmentSync::new();
    if let Err(e) = env_sync.ensure_synced(&project_dir) {
        tracing::warn!("Environment sync check failed: {}", e);
        // Non-fatal: continue execution
    }

    // 3.6 RFC-0018: Autopilot decision (check if Zygote should be auto-enabled)
    let autopilot = AutopilotEngine::default();
    let autopilot_decision = autopilot.should_use_zygote(script_path);
    let autopilot_enabled = matches!(
        autopilot_decision,
        AutopilotDecision::EnabledByStatic { .. } | AutopilotDecision::EnabledByPerformance { .. }
    );

    if cmd.profile {
        match &autopilot_decision {
            AutopilotDecision::EnabledByStatic { modules } => {
                eprintln!("[VELO] Autopilot: Enabled (heavy imports: {:?})", modules);
            }
            AutopilotDecision::EnabledByPerformance { avg_cold_start_ms } => {
                eprintln!(
                    "[VELO] Autopilot: Enabled (avg cold start: {}ms)",
                    avg_cold_start_ms
                );
            }
            _ => {}
        }
    }

    // 4. Zygote/Fast/Normal run (includes autopilot decision)
    if cmd.zygote_enabled() || autopilot_enabled {
        let _zygote_start = std::time::Instant::now();
        // Create SHM segment if requested
        let shm_file = if let Some(ref shm_path) = cmd.shm {
            let registry = MemoryRegistry::new(config.clone());
            let segment_name = format!("shm-{}-{}", std::process::id(), 0); // TODO: unique name?
            match registry.create_segment(&segment_name, shm_path) {
                Ok(seg) => Some(seg),
                Err(e) => {
                    let signal = crate::common::governance::GovernanceSignal::new(
                        crate::common::governance::SignalComponent::MemoryGravity,
                        format!("SHM Segment creation failed: {}", e),
                        "Sub-optimal performance (Disk-loading fallback)",
                        "Verify file permissions and SHM limits (max_shm_size).",
                    );

                    if config.strict_optimizations {
                        bail!("{}", signal.format_critical());
                    } else {
                        signal.report_audit();
                        None
                    }
                }
            }
        } else {
            None
        };

        let zygote_result = match try_zygote_run(
            &python_path,
            Some(script_path_str),
            None,
            &cmd.args.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            cmd.async_mode,
            cmd.fast,
            &project_dir,
            &config,
            cmd.profile,
            shm_file.as_ref().map(|s| &s.file),
        ) {
            Ok(res) => res,
            Err(e) => {
                let signal = crate::common::governance::GovernanceSignal::new(
                    crate::common::governance::SignalComponent::ZygoteIPC,
                    format!("Zygote fundamental failure: {}", e),
                    "Performance degradation (Cold Start fallback)",
                    "Check Zygote status and socket permissions.",
                );
                if config.strict_optimizations {
                    bail!("{}", signal.format_critical());
                } else {
                    signal.report_audit();
                    None
                }
            }
        };

        if let Some(()) = zygote_result {
            if cmd.profile {
                eprintln!(
                    "[VELO] Zygote Total: {:.1}ms, Total E2E: {:.1}ms",
                    _zygote_start.elapsed().as_secs_f64() * 1000.0,
                    _total_start.elapsed().as_secs_f64() * 1000.0
                );
            }
            return Ok(());
        }

        // If we reach here, try_zygote_run returned None (Fallback triggered)
        let signal = crate::common::governance::GovernanceSignal::new(
            crate::common::governance::SignalComponent::ZygoteIPC,
            "Zygote process failed to initialize or spawn worker",
            "Performance degradation (Cold Start latency added)",
            "Check Zygote logs with 'velo zygote status' and verify socket permissions.",
        );

        if config.strict_optimizations {
            bail!("{}", signal.format_critical());
        } else {
            signal.report_audit();
        }
    }

    // Normal mode (or fallback)
    let (pythonpath, needs_capture) = python::setup_python_env(&project_dir, &python_path);

    // AI-Native Diagnostics (RFC-0038)
    if let Some(prof_md_path) = &cmd.prof_md {
        let (status, total_time, profile_data) = runner::run_script_with_profile_capture(
            &python_path,
            script_path_str,
            pythonpath.clone(),
            &config,
        )?;

        let timeline = StartupTimeline {
            zygote_ms: _discovery_time.as_millis() as u64
                + _config_time.as_millis() as u64
                + _python_time.as_millis() as u64,
            app_entry_ms: total_time.as_millis() as u64 / 10,
            total_ms: total_time.as_millis() as u64,
        };

        let formatter = MarkdownFormatter::new("Velo Diagnostic Report");
        let env_map: HashMap<String, String> = std::env::vars().collect();
        let sanitized_env = MarkdownFormatter::sanitize_env(&env_map);

        let (bottlenecks, memory_delta_mb) = if let Some(pd) = profile_data {
            (pd.to_slow_imports(20), pd.memory_delta_mb)
        } else {
            (Vec::new(), 0.0)
        };

        let report = formatter.format_report(
            total_time,
            memory_delta_mb,
            &sanitized_env,
            bottlenecks,
            timeline,
        );
        MarkdownFormatter::write_atomic(prof_md_path, &report)?;

        eprintln!("📝 Diagnostic report written to {}", prof_md_path.display());

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }
        return Ok(());
    }

    // AI-Native Diagnostics JSON format (RFC-0038 GAP-3)
    if let Some(prof_json_path) = &cmd.prof_json {
        let (status, total_time, profile_data) = runner::run_script_with_profile_capture(
            &python_path,
            script_path_str,
            pythonpath.clone(),
            &config,
        )?;

        let timeline = StartupTimeline {
            zygote_ms: _discovery_time.as_millis() as u64
                + _config_time.as_millis() as u64
                + _python_time.as_millis() as u64,
            app_entry_ms: total_time.as_millis() as u64 / 10,
            total_ms: total_time.as_millis() as u64,
        };

        let formatter = MarkdownFormatter::new("Velo Diagnostic Report");
        let env_map: HashMap<String, String> = std::env::vars().collect();
        let sanitized_env = MarkdownFormatter::sanitize_env(&env_map);

        let (bottlenecks, memory_delta_mb) = if let Some(pd) = profile_data {
            (pd.to_slow_imports(20), pd.memory_delta_mb)
        } else {
            (Vec::new(), 0.0)
        };

        let report = formatter.format_json(
            total_time,
            memory_delta_mb,
            &sanitized_env,
            bottlenecks,
            timeline,
        );
        // BUG-002 & BUG-003 FIX: JSON也使用原子写入(包含ANSI stripping)
        MarkdownFormatter::write_atomic(prof_json_path, &report)?;

        eprintln!(
            "📝 JSON diagnostic report written to {}",
            prof_json_path.display()
        );

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }
        return Ok(());
    }

    // Fast mode: inject sitecustomize to activate bundle loader
    if cmd.fast {
        if let Err(e) = run_with_fast_loader(
            &python_path,
            script_path_str,
            &project_dir,
            pythonpath,
            Some(config.max_bundle_size as u64),
            &config,
        ) {
            let signal = crate::common::governance::GovernanceSignal::new(
                crate::common::governance::SignalComponent::FastLoader,
                format!("Fast loader initialization failed: {}", e),
                "Slow Startup (Standard imports used)",
                "Verify bundle integrity with 'velo bundle verify'.",
            );
            if config.strict_optimizations {
                bail!("{}", signal.format_critical());
            } else {
                signal.report_audit();
                runner::run_script(&python_path, script_path_str, None, &config)?;
            }
        }
    } else if cmd.profile {
        runner::run_script_with_profile(&python_path, script_path_str, pythonpath, &config)?;
    } else {
        runner::run_script(&python_path, script_path_str, pythonpath, &config)?;
    }

    // If we didn't have cache, capture sys.path for next time
    if needs_capture {
        save_cache_if_needed(&project_dir, &python_path);
    }

    Ok(())
}

/// RFC-0030: Run a Python module (like python -m module_name)
///
/// This enables Jupyter kernel execution via:
///   velo run -m ipykernel_launcher -f {connection_file}
fn run_module_impl(cmd: &RunCmd) -> Result<()> {
    use crate::lifecycle::{EnvironmentShield, apply_standard_hygiene};
    use std::process::Command;

    let module_name = cmd.module.as_ref().unwrap(); // guaranteed by clap validation
    let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));

    // Load config
    let config = VeloConfig::load_with_overrides(&VeloPaths::pyproject(&project_dir));

    // Detect Python
    let python_path = python::detect_python(&project_dir)?;

    // Build command: python -m <module> [args...]
    // RFC-0030: Jupyter Integration acceleration logic
    // RFC-0030: Consolidate positional 'script' and trailing 'args'
    // When -m is used, the first positional argument (script) is actually the first arg for the module
    let mut all_args = Vec::new();
    if let Some(s) = &cmd.script {
        all_args.push(s.as_str());
    }
    for arg in &cmd.args {
        all_args.push(arg.as_str());
    }

    // If zygote is requested or it's a known heavy module (like ipykernel), try zygote
    if cmd.zygote_enabled() {
        match try_zygote_run(
            &PathBuf::from(&python_path),
            None,
            Some(module_name.clone()),
            &all_args,
            cmd.async_mode,
            cmd.fast,
            &project_dir,
            &config,
            cmd.profile,
            None, // shm_file
        ) {
            Ok(Some(())) => return Ok(()),
            Ok(None) => {
                // Zygote not available or failed to start, fallback already logged/printed
            }
            Err(e) => {
                eprintln!(
                    "⚠️ Zygote acceleration failed: {}. Falling back to native.",
                    e
                );
            }
        }
    }

    // AI-Native Diagnostics (RFC-0038)
    if let Some(prof_md_path) = &cmd.prof_md {
        let (status, total_time, profile_data) = runner::run_module_with_profile_capture(
            &PathBuf::from(&python_path),
            module_name,
            &all_args,
            &config,
        )?;

        let timeline = StartupTimeline {
            zygote_ms: 50, // heuristic for module mode overhead
            app_entry_ms: total_time.as_millis() as u64 / 10,
            total_ms: total_time.as_millis() as u64,
        };

        let formatter = MarkdownFormatter::new("Velo Diagnostic Report (Module)");
        let env_map: HashMap<String, String> = std::env::vars().collect();
        let sanitized_env = MarkdownFormatter::sanitize_env(&env_map);

        let (bottlenecks, memory_delta_mb) = if let Some(pd) = profile_data {
            (pd.to_slow_imports(20), pd.memory_delta_mb)
        } else {
            (Vec::new(), 0.0)
        };

        let report = formatter.format_report(
            total_time,
            memory_delta_mb,
            &sanitized_env,
            bottlenecks,
            timeline,
        );
        MarkdownFormatter::write_atomic(prof_md_path, &report)?;

        eprintln!("📝 Diagnostic report written to {}", prof_md_path.display());

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }
        return Ok(());
    }

    let mut py_cmd = Command::new(&python_path);

    // RFC-0012: Surgical Environment Management
    let shield = EnvironmentShield::new(&config);
    shield.apply(&mut py_cmd).map_err(anyhow::Error::msg)?;

    // RFC-0012 §3.6: FD & Signal Hygiene (critical for Jupyter kernel)
    // This ensures SIGINT forwarding and FD cleanup per RFC-0030 §9.1
    apply_standard_hygiene(&mut py_cmd);

    // Inject environment variables
    py_cmd.env(
        "VELO_GRACEFUL_SHUTDOWN_TIMEOUT",
        config.graceful_shutdown_timeout.to_string(),
    );
    py_cmd.env(
        "VELO_SOCKET_STARTUP_TIMEOUT",
        config.zygote_socket_timeout.to_string(),
    );

    // Build args: -m module_name [trailing args...]
    py_cmd.arg("-m").arg(module_name);

    // Pass through consolidated arguments
    for arg in all_args {
        py_cmd.arg(arg);
    }

    if cmd.profile {
        eprintln!(
            "[VELO] Module execution: python -m {} {:?}",
            module_name, cmd.args
        );
    }

    // Execute and wait
    let status = py_cmd
        .status()
        .map_err(|e| anyhow::anyhow!("Failed to run module {}: {}", module_name, e))?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

/// Try to run via Zygote, returns Some(()) on success, None on failure
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
fn try_zygote_run(
    python_path: &Path,
    script_path: Option<&str>,
    module_name: Option<String>,
    args: &[&str],
    async_enabled: bool,
    fast_enabled: bool,
    project_dir: &Path,
    config: &VeloConfig,
    profile: bool,
    shm_file: Option<&std::fs::File>,
) -> Result<Option<()>> {
    use crate::zygote;

    if !zygote::is_supported() {
        return Ok(None);
    }

    let socket_path = zygote::core_ipc::default_socket_path();
    let script = script_path
        .map(Path::new)
        .unwrap_or_else(|| Path::new(python_path));

    // config is already loaded and passed in
    let _timeout = config.zygote_socket_timeout;

    // Check if Zygote is running, start if not (hybrid mode)
    let mut launcher =
        ZygoteLauncher::new(socket_path.clone()).with_python(python_path.to_path_buf());

    let preload: Vec<&str> = config.preload.iter().map(|s| s.as_str()).collect();
    let started_new = if !socket_path.exists() {
        if profile {
            if preload.is_empty() {
                eprintln!("🚀 Starting Zygote...");
            } else {
                eprintln!("🚀 Starting Zygote with preload: {:?}", preload);
            }
        }

        if let Err(e) = launcher.start(&preload, None, true, config) {
            if config.strict_optimizations {
                return Err(e.into());
            }
            eprintln!("⚠️ Failed to start Zygote: {}", e);
            eprintln!("   Falling back to normal mode");
            return Ok(None);
        }
        if profile {
            eprintln!("✅ Zygote ready");
        }
        true
    } else {
        false
    };

    // Try to spawn via Zygote
    if socket_path.exists() {
        let (bundle_path, max_size) = if fast_enabled {
            (
                find_bundle(project_dir, script.to_str().unwrap_or("")),
                Some(config.max_bundle_size as u64),
            )
        } else {
            (None, None)
        };

        match launcher.spawn_worker(
            script,
            module_name.clone(),
            args,
            async_enabled,
            fast_enabled,
            bundle_path.clone(),
            Some(project_dir.to_path_buf()),
            max_size,
            shm_file,
            None, // env_overrides
            config,
        ) {
            Ok(worker) => {
                if async_enabled {
                    println!("Worker PID: {}", worker.pid());
                    eprintln!("⚡ Worker spawned in background (PID: {})", worker.pid());
                    if profile {
                        if let Some(stdout) = worker.stdout_path() {
                            eprintln!("📝 Logs (stdout): {}", stdout.display());
                        }
                        if let Some(stderr) = worker.stderr_path() {
                            eprintln!("📝 Logs (stderr): {}", stderr.display());
                        }
                    }

                    // Keep Zygote alive but exit CLI immediately
                    if started_new {
                        std::mem::forget(launcher);
                    }
                    std::process::exit(0);
                }

                eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());
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
                // Check if this is a stale socket (connection refused)
                let is_stale = e.to_string().contains("Connection refused")
                    || e.to_string().contains("Connection failed")
                    || e.to_string().contains("Broken pipe");

                if is_stale && !started_new {
                    // Stale socket - remove and restart Zygote
                    eprintln!("🔄 Stale socket detected, restarting Zygote...");
                    zygote::core_ipc::cleanup_socket(&socket_path);

                    if let Ok(()) = launcher.start(&preload, None, true, config) {
                        eprintln!("✅ Zygote ready");

                        // Retry spawn
                        let (bundle_path, max_size) = if fast_enabled {
                            (
                                find_bundle(project_dir, script.to_str().unwrap_or("")),
                                Some(config.max_bundle_size as u64),
                            )
                        } else {
                            (None, None)
                        };

                        if let Ok(worker) = launcher.spawn_worker(
                            script,
                            module_name,
                            args,
                            async_enabled,
                            fast_enabled,
                            bundle_path,
                            Some(project_dir.to_path_buf()),
                            max_size,
                            shm_file,
                            None, // env_overrides
                            config,
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

                    // Final fallback
                    if config.strict_optimizations {
                        return Err(e.into());
                    }
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
        VeloPaths::project_file(project_dir, VELO_CACHE_DIR).join("bundle.veloc"),
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
    config: &VeloConfig,
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
                return runner::run_script(python_path, script_path, pythonpath, config);
            }
        };

        // RFC-0008: Mandatory Security Pre-validation (H-1, H-2, H-4, H-5)
        // This provides a structural lock at the Rust boundary.
        if let Err(e) = crate::loader::verify::load_and_verify(&actual_bundle, max_bundle_size) {
            eprintln!("⚠️  Fast loader security check failed: {}", e);
            eprintln!("   Falling back to normal imports...");
            return runner::run_script(python_path, script_path, pythonpath, config);
        }

        eprintln!("⚡ Fast mode: loading from {}", actual_bundle.display());

        let bundle_abs = actual_bundle.canonicalize()?;
        let project_abs = project_dir.canonicalize()?;

        // Create a unique temporary directory for sitecustomize.py
        // RFC-0006: Injects sitecustomize.py to activate VeloBundle import hook
        let temp_dir = tempfile::tempdir()?;
        let site_file = VeloPaths::site_customize(temp_dir.path());

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
            .find(|p| VeloPaths::project_file(p, VELO_LOADER).exists())
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
        runner::run_script(python_path, script_path, Some(enhanced_pythonpath), config)
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
        assert_eq!(cmd.script, Some("script.py".to_string()));
        assert!(!cmd.zygote);
        assert!(!cmd.async_mode);
        assert!(!cmd.profile);
        assert!(!cmd.fast);
        assert!(!cmd.is_module_mode());
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
        // Now requires a script OR module (-m)
        let result = RunCmd::try_parse_from(["run"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_module_mode() {
        // RFC-0030: Module execution
        let cmd = RunCmd::try_parse_from(["run", "-m", "ipykernel_launcher"]).unwrap();
        assert!(cmd.is_module_mode());
        assert_eq!(cmd.module, Some("ipykernel_launcher".to_string()));
        assert!(cmd.script.is_none());
    }

    #[test]
    fn test_parse_module_with_args() {
        // RFC-0030: Module with trailing args (for Jupyter -f connection_file)
        // Use -- to separate velo options from module args
        // Note: First positional after -- goes to args (no script when -m is used)
        let cmd = RunCmd::try_parse_from([
            "run",
            "-m",
            "ipykernel_launcher",
            "--",
            "-f",
            &std::env::temp_dir().join("kernel.json").to_string_lossy(),
        ])
        .unwrap();
        assert!(cmd.is_module_mode());
        // Check that trailing args are captured
        // The first positional ("-f") goes to script when present, but we have -m so script should be None
        assert!(cmd.script.is_none() || cmd.script == Some("-f".to_string()));
        // Remaining args should be in args vec
        assert!(!cmd.args.is_empty());
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
        File::create(VeloPaths::pyproject(project_root))?;

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
        let found = VeloPaths::pyproject(&project_root.join(p)).exists();
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
