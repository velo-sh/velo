//! Handle 'velo debug' command and subcommands
//!
//! RFC-0020: Zygote Observability

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use std::path::Path;
use std::time::Duration;

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use crate::python;
use crate::zygote::{ZygoteLauncher, ipc};

#[derive(Parser, Debug)]
#[command(name = "debug", about = "Access internal debugging tools")]
pub struct DebugCmd {
    #[command(subcommand)]
    pub command: DebugSubcommand,
}

#[derive(Subcommand, Debug)]
pub enum DebugSubcommand {
    /// Run Zygote pre-flight checks
    Zygote {
        #[arg(long, short)]
        verbose: bool,
        #[arg(long)]
        json: bool,
    },
}

pub fn cmd_debug(args: &[String]) -> Result<()> {
    let cmd = DebugCmd::try_parse_from(&args[1..])?;
    match cmd.command {
        DebugSubcommand::Zygote { verbose, json } => cmd_debug_zygote(verbose, json),
    }
}

fn cmd_debug_zygote(verbose: bool, json: bool) -> Result<()> {
    let project_dir = std::env::current_dir()?;
    let python_path = python::detect_python(&project_dir)?;

    // 1. Run Python-side preflight (Steps 1-3)
    // We run this first as it validates the environment for the Zygote
    run_python_preflight(&python_path, &project_dir, verbose, json)?;

    // 2. Run Rust-side preflight (Zygote lifecycle: Steps 4-7)
    if !json {
        println!("\n[4/4] Zygote Lifecycle Test");
    }

    // Use a temporary socket path
    // We use a random name to avoid conflicts
    let socket_name = format!("velo-debug-{}.sock", uuid::Uuid::new_v4());
    let socket_path = std::env::temp_dir().join(socket_name);

    // Cleanup ensures socket is removed even on panic/error
    let _cleanup = SocketCleanup {
        path: socket_path.clone(),
    };

    // Load config
    let config = VeloConfig::load_with_overrides(&VeloPaths::pyproject(&project_dir));

    // Initialize Launcher
    let mut launcher = ZygoteLauncher::new(socket_path.clone()).with_python(python_path.clone());

    if !json && verbose {
        println!(
            "      • Spawning Zygote (socket: {})...",
            socket_path.display()
        );
    }

    // Start Zygote (foreground=false, but we will stop it manually)
    // We pass empty preload list
    launcher
        .start(&[], None, false, &config)
        .context("Failed to start Zygote process")?;

    // Wait for socket with timeout
    let start = std::time::Instant::now();
    let timeout = Duration::from_secs(5);
    let mut socket_ready = false;

    while start.elapsed() < timeout {
        if socket_path.exists() {
            socket_ready = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    if !socket_ready {
        // Try to read stderr from child if possible?
        // Launcher::start detaches or keeps child. In current impl, it might detach.
        bail!("Timed out waiting for Zygote socket creation (>5s)");
    }

    if !json {
        println!("      • Socket created: ✅");
    }

    // Perform Handshake
    let handshake_cmd = ipc::ZygoteCommand::Handshake {
        version: ipc::PROTOCOL_VERSION,
        capabilities: vec!["debug".to_string()],
        request_id: Some(uuid::Uuid::now_v7().to_string()),
    };

    match ipc::send_command(&socket_path, handshake_cmd, None) {
        Ok(ipc::ZygoteResponse::Handshake {
            version,
            capabilities,
        }) => {
            if !json {
                println!(
                    "      • Handshake: ✅ (v{}, capabilities: {:?})",
                    version, capabilities
                );
            }
        }
        Ok(resp) => {
            let _ = launcher.stop();
            bail!("Unexpected handshake response: {:?}", resp);
        }
        Err(e) => {
            let _ = launcher.stop();
            bail!("Handshake failed: {}", e);
        }
    }

    // Stop Zygote
    launcher.stop()?;

    if !json {
        println!("✅ Zygote lifecycle checks PASSED");
    }

    Ok(())
}

fn run_python_preflight(
    python_path: &Path,
    _project_dir: &Path,
    verbose: bool,
    json: bool,
) -> Result<()> {
    let mut cmd = std::process::Command::new(python_path);
    cmd.arg("-m").arg("velo_zygote.preflight");

    if verbose {
        cmd.arg("--verbose");
    }
    if json {
        cmd.arg("--json");
    }

    // Environment defaults are handled by Python Bootstrap (SSOT)
    // We only pass explicit environment variables.

    // Inherit stdout/stderr so output is visible
    cmd.stdout(std::process::Stdio::inherit());
    cmd.stderr(std::process::Stdio::inherit());

    let status = cmd
        .status()
        .context("Failed to execute python preflight script")?;

    if !status.success() {
        bail!("Python pre-flight checks failed");
    }

    Ok(())
}

struct SocketCleanup {
    path: std::path::PathBuf,
}

impl Drop for SocketCleanup {
    fn drop(&mut self) {
        if self.path.exists() {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}
