//! Handle 'velo debug' command and subcommands
//!
//! RFC-0020: Zygote Observability

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use std::path::Path;

use crate::cmd::cmd_debug_pre_flight;
use velo_core::common::paths::VeloPaths;
use velo_core::config::VeloConfig;

use velo_core::zygote::ZygoteLauncher;

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
    /// Run environmental pre-flight checks
    PreFlight {
        #[arg(long)]
        json: bool,
    },
}

pub fn cmd_debug(args: &[String]) -> Result<()> {
    let cmd = DebugCmd::try_parse_from(&args[1..])?;
    match cmd.command {
        DebugSubcommand::Zygote { verbose, json } => cmd_debug_zygote(verbose, json),
        DebugSubcommand::PreFlight { json } => cmd_debug_pre_flight(json),
    }
}

fn cmd_debug_zygote(verbose: bool, json: bool) -> Result<()> {
    let project_dir = std::env::current_dir()?;
    let python_path = velo_core::python::detect_python(&project_dir)?;

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
    // launcher.start() internally:
    // 1. Creates the listener socket
    // 2. Spawns Python bootstrap
    // 3. Accepts connection from Python
    // 4. Performs handshake
    // 5. Verifies Status
    // If start() returns Ok, the Zygote is fully ready.
    launcher
        .start(&[], None, false, &config)
        .context("Failed to start Zygote process")?;

    if !json {
        println!("      • Socket created: ✅");
        println!("      • Handshake: ✅ (performed by launcher.start())");
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
    // RFC-0012: Ensure python/ directory is in PYTHONPATH for internal modules
    if let Ok(cwd) = std::env::current_dir() {
        cmd.env("PYTHONPATH", cwd.join("python"));
    } else {
        cmd.env("PYTHONPATH", "python");
    }

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
