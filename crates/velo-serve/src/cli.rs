//! Handle 'velo serve' command
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::Result;
use clap::Parser;
use std::path::{Path, PathBuf};
use velo_core::common::paths::VeloPaths;

use velo_core::python;

use crate::config::{LogFormat, ServeArgs};

/// Custom parser for workers argument with clear error messages
fn parse_workers(s: &str) -> Result<u32, String> {
    let n = s
        .parse::<i64>()
        .map_err(|_| format!("invalid worker count '{}': must be a valid number", s))?;
    if n < 1 {
        return Err(format!("invalid worker count '{}': must be at least 1", s));
    }
    if n > u32::MAX as i64 {
        return Err(format!(
            "invalid worker count '{}': exceeds maximum value {}",
            s,
            u32::MAX
        ));
    }
    Ok(n as u32)
}

/// Custom parser for port argument with clear error messages
fn parse_port(s: &str) -> Result<u16, String> {
    let n = s
        .parse::<i64>()
        .map_err(|_| format!("invalid port '{}': must be a valid number", s))?;
    if !(1..=65535).contains(&n) {
        return Err(format!("invalid port '{}': must be between 1 and 65535", s));
    }
    Ok(n as u16)
}

/// Serve a Python ASGI/WSGI application
#[derive(Parser, Debug)]
#[command(name = "serve", about = "Serve a Python ASGI/WSGI application")]
pub struct ServeCmd {
    /// Application path (e.g., 'main:app', 'myapp.main:create_app()')
    #[arg()]
    pub app: Option<String>,

    /// Bind host
    #[arg(long, default_value = "127.0.0.1")]
    pub host: String,

    /// Bind port
    #[arg(long, default_value_t = 8000, value_parser = parse_port)]
    pub port: u16,

    /// Shorthand for --host and --port (e.g., 0.0.0.0:8080)
    #[arg(long, value_name = "HOST:PORT")]
    pub bind: Option<String>,

    /// Number of workers (default: 1, auto in --prod)
    #[arg(long, default_value_t = 1, value_parser = parse_workers, allow_hyphen_values = true)]
    pub workers: u32,

    /// Graceful shutdown timeout in seconds
    #[arg(long, default_value_t = 20)]
    pub timeout: u64,

    /// Health check endpoint (e.g., 0.0.0.0:8081)
    #[arg(long, value_name = "ADDR")]
    pub health_bind: Option<String>,

    /// Write PID file for process management
    #[arg(long, value_name = "PATH")]
    pub pid_file: Option<PathBuf>,

    /// Output format: text (default) or json
    #[arg(
        long,
        value_name = "FMT",
        default_value = "text",
        alias = "output-format"
    )]
    pub log_format: String,

    /// Set verbosity level (can be used multiple times)
    #[arg(short, long, action = clap::ArgAction::Count)]
    pub verbose: u8,

    /// Dry run mode (log command and exit)
    #[arg(long)]
    pub dry_run: bool,

    /// Enable hot reload (disabled in --prod)
    #[arg(long)]
    pub reload: bool,

    /// Production mode (no reload, auto workers)
    #[arg(long)]
    pub prod: bool,

    /// Enable Zygote pre-warming (default)
    #[arg(long, alias = "use-zygote", conflicts_with = "no_zygote")]
    pub zygote: bool,

    /// Disable Zygote pre-warming
    #[arg(long)]
    pub no_zygote: bool,

    /// Force RSGI mode (RFC-0019)
    #[arg(long)]
    pub rsgi: bool,

    /// Enable Vibe Coding mode (real-time hot reload) [RFC-0029]
    #[arg(long)]
    pub vibe: bool,

    /// Alias for --vibe
    #[arg(long)]
    pub live: bool,
}

impl ServeCmd {
    /// Convert clap args to ServeArgs
    pub fn to_serve_args(&self) -> Result<ServeArgs> {
        let mut args = ServeArgs::new(self.app.clone().unwrap_or_default());

        // Handle --bind shorthand
        if let Some(ref bind) = self.bind {
            if let Some((host, port)) = bind.rsplit_once(':') {
                args.host = host.to_string();
                args.port = port
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid port in bind address '{}'", bind))?;
            } else {
                anyhow::bail!("--bind requires HOST:PORT format (e.g., 0.0.0.0:8080)");
            }
        } else {
            args.host = self.host.clone();
            args.port = self.port;
        }

        args.workers = self.workers;
        args.timeout = self.timeout;
        args.health_bind = self.health_bind.clone();
        args.pid_file = self.pid_file.clone();
        args.reload = self.reload;
        // Gate 7.2: Zygote is enabled by default unless --no-zygote is specified.
        // Support --use-zygote (explicitly enabled) as well.
        args.use_zygote = !self.no_zygote || self.zygote;

        // Parse log format
        args.log_format = match self.log_format.as_str() {
            "text" => LogFormat::Text,
            "json" => LogFormat::Json,
            other => anyhow::bail!("unknown log format '{}'. Use 'text' or 'json'", other),
        };

        args.verbose = self.verbose;
        args.dry_run = self.dry_run;
        args.rsgi = self.rsgi;

        // Apply prod mode settings
        args.apply_prod_mode();

        // Validate (SEC-P0-001)
        args.validate()?;

        Ok(args)
    }
}

#[derive(serde::Deserialize)]
struct DetectedApp {
    module: String,
    app: String,
}

pub fn find_python_helper(project_dir: &Path, name: &str) -> Option<PathBuf> {
    // 1. Check project_dir/python/name (user's project or current repo)
    let path = project_dir.join("python").join(name);
    if path.exists() {
        return Some(path);
    }

    // 2. Try walking up from project_dir
    let mut current = project_dir.to_path_buf();
    while let Some(parent) = current.parent() {
        let path = parent.join("python").join(name);
        if path.exists() {
            return Some(path);
        }
        current = parent.to_path_buf();
    }
    // 2. Check relative to executable (installed or dev layout)
    if let Ok(exe_path) = std::env::current_exe() {
        let mut current = exe_path.to_path_buf();
        while let Some(parent) = current.parent() {
            let path = parent.join("python").join(name);
            if path.exists() {
                return Some(path);
            }
            // Also check for 'python' dir in parent's siblings (for target/debug layout)
            let path = parent.join("..").join("python").join(name);
            if path.exists() {
                return Some(path);
            }
            current = parent.to_path_buf();
        }
    }

    None
}

fn discover_app(python_path: &Path, project_dir: &Path) -> Result<String> {
    let script_path = find_python_helper(project_dir, "detect_app.py")
        .ok_or_else(|| anyhow::anyhow!("Internal error: could not find detect_app.py"))?;

    let output = std::process::Command::new(python_path)
        .arg(&script_path)
        .arg("--output")
        .arg("json")
        .current_dir(project_dir)
        .output()?;

    if !output.status.success() {
        anyhow::bail!("No ASGI/WSGI app detected. Please specify one: velo serve main:app");
    }

    let apps: Vec<DetectedApp> = serde_json::from_slice(&output.stdout)?;
    if apps.is_empty() {
        anyhow::bail!("No ASGI/WSGI app detected. Please specify one: velo serve main:app");
    }

    // Default to the first (highest priority) one
    Ok(format!("{}:{}", apps[0].module, apps[0].app))
}

#[allow(dead_code)]
fn suggest_app(target: &str, python_path: &Path, project_dir: &Path) -> Option<String> {
    let script_path = find_python_helper(project_dir, "detect_app.py")?;
    let output = std::process::Command::new(python_path)
        .arg(&script_path)
        .arg("--output")
        .arg("json")
        .current_dir(project_dir)
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let apps: Vec<DetectedApp> = serde_json::from_slice(&output.stdout).ok()?;
    let mut best_match = None;
    let mut min_dist = 2; // MANDATE OBS-001: Max threshold 2

    for app in apps {
        let full_name = format!("{}:{}", app.module, app.app);
        let dist = strsim::levenshtein(target, &full_name);
        if dist > 0 && dist <= min_dist {
            min_dist = dist;
            best_match = Some(full_name);
        }
    }

    best_match
}

/// Run serve in Vibe Coding mode (RFC-0029)
///
/// This starts the VibeEngine with the app as the target.
#[tokio::main]
async fn run_vibe_serve_mode(cmd: &ServeCmd) -> Result<()> {
    use crate::v_live::engine::VibeEngine;
    use colored::Colorize;

    let app = cmd.app.clone().unwrap_or_else(|| "main:app".to_string());
    let gateway_addr = format!("{}:{}", cmd.host, cmd.port);

    println!(
        "{}",
        "🏛️  Vibe Engine (Serve Mode) Activated".green().bold()
    );
    println!("Architecture Directive: Phase 8 (Vibe-Coding)");
    println!("App: {}", app);

    // For serve mode, we watch the module file corresponding to the app
    let (module, _) = app.split_once(':').unwrap_or((&app, "app"));
    let target = PathBuf::from(format!("{}.py", module.replace('.', "/")));

    let engine = VibeEngine::new(target, &gateway_addr);
    engine.start().await?;

    Ok(())
}

pub fn cmd_serve(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo serve" prefix
    let cmd = ServeCmd::try_parse_from(&args[1..])?;

    // RFC-0029/GAP-001: Vibe mode takes precedence
    if cmd.vibe || cmd.live {
        return run_vibe_serve_mode(&cmd);
    }

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Handle auto-discovery if app is not provided
    let mut cmd = cmd;
    if cmd.app.is_none() {
        match discover_app(&python_path, &project_dir) {
            Ok(app) => {
                eprintln!("✨ Detected app: {}", app);
                cmd.app = Some(app);
            }
            Err(e) => return Err(e),
        }
    }

    // Convert to ServeArgs
    let serve_args = cmd.to_serve_args()?;

    // Load config (Phase 6 security)
    let config =
        velo_core::config::VeloConfig::load_with_overrides(&VeloPaths::pyproject(&project_dir));

    // TITANIUM RULE: Audit Reporting (P3-001)
    print_governance_table(&serve_args, &config, &project_dir);

    // Run the server with reload loop (RFC-0010)
    while let crate::runner::ServerExit::Reload =
        crate::run_server(&serve_args, &python_path, &project_dir, &config)?
    {
        // Determine restart behavior
        // On reload, we loop and call run_server again.
        // run_server will spawn a fresh uvicorn/zygote.
        eprintln!("🔄 Restarting server...");
    }

    #[cfg(unix)]
    if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
        crate::runner::cleanup_test_processes(&project_dir, &serve_args.app);
    }

    Ok(())
}

fn print_governance_table(
    args: &ServeArgs,
    config: &velo_core::config::VeloConfig,
    project_dir: &Path,
) {
    use colored::Colorize;

    println!("\n{}", "TITANIUM GOVERNANCE AUDIT".white().bold().on_blue());
    println!("{:<25} Value", "Parameter".bold());
    println!("{}", "─".repeat(60));

    // Runtime Isolation
    println!(
        "{:<25} {}",
        "Runtime Mode",
        if args.use_zygote {
            "Zygote (Zero-Config)"
        } else {
            "Legacy (Subprocess)"
        }
    );
    println!(
        "{:<25} {}",
        "Auto-Sync",
        if config.auto_sync_enabled {
            "Enabled".green()
        } else {
            "Disabled".yellow()
        }
    );
    println!(
        "{:<25} {}",
        "Circuit Breaker",
        if config.circuit_breaker_enabled {
            "Active".green()
        } else {
            "Disabled".red()
        }
    );

    // Security
    let isolation = if cfg!(target_os = "linux") && config.strict_optimizations {
        "Namespaced".green()
    } else {
        "Standard".yellow()
    };
    println!("{:<25} {}", "Isolation Level", isolation);
    println!("{:<25} {}", "Airlock Threads", config.security_hpc_threads);

    // Project
    println!("{:<25} {:?} (Secure)", "Project Root", project_dir);

    println!("{}", "─".repeat(60));
    println!();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_basic() {
        let cmd = ServeCmd::try_parse_from(["serve", "main:app"]).unwrap();
        assert_eq!(cmd.app.as_deref(), Some("main:app"));
        assert_eq!(cmd.host, "127.0.0.1");
        assert_eq!(cmd.port, 8000);
    }

    #[test]
    fn test_parse_with_options() {
        let cmd = ServeCmd::try_parse_from([
            "serve",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--workers",
            "4",
        ])
        .unwrap();
        assert_eq!(cmd.app.as_deref(), Some("main:app"));
        assert_eq!(cmd.host, "0.0.0.0");
        assert_eq!(cmd.port, 8080);
        assert_eq!(cmd.workers, 4);
    }

    #[test]
    fn test_parse_bind_shorthand() {
        let cmd =
            ServeCmd::try_parse_from(["serve", "main:app", "--bind", "0.0.0.0:9000"]).unwrap();
        let args = cmd.to_serve_args().unwrap();
        assert_eq!(args.host, "0.0.0.0");
        assert_eq!(args.port, 9000);
    }

    #[test]
    fn test_parse_prod_mode() {
        let cmd = ServeCmd::try_parse_from(["serve", "main:app", "--prod"]).unwrap();
        assert!(cmd.prod);
    }

    #[test]
    fn test_parse_no_zygote() {
        let cmd = ServeCmd::try_parse_from(["serve", "main:app", "--no-zygote"]).unwrap();
        assert!(cmd.no_zygote);
        let args = cmd.to_serve_args().unwrap();
        assert!(!args.use_zygote);
    }

    #[test]
    fn test_missing_app_ok() {
        let result = ServeCmd::try_parse_from(["serve"]);
        assert!(result.is_ok());
        let cmd = result.unwrap();
        assert!(cmd.app.is_none());
    }

    #[test]
    fn test_unknown_option_error() {
        let result = ServeCmd::try_parse_from(["serve", "main:app", "--unknown"]);
        assert!(result.is_err());
    }
}
