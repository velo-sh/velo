//! Handle 'velo zygote' command and subcommands
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::{Result, bail};
use clap::{Parser, Subcommand};
use std::path::Path;

use crate::common::paths::VeloPaths;
use crate::python;
use crate::zygote::{self, ZygoteLauncher};

/// Zygote daemon management
#[derive(Parser, Debug)]
#[command(name = "zygote", about = "Manage Zygote pre-warming daemon")]
pub struct ZygoteCmd {
    #[command(subcommand)]
    pub command: ZygoteSubcommand,
}

#[derive(Subcommand, Debug)]
pub enum ZygoteSubcommand {
    /// Start Zygote daemon
    Start {
        /// Comma-separated list of modules to preload
        #[arg(long)]
        preload: Option<String>,
    },
    /// Stop Zygote daemon
    Stop,
    /// Show Zygote status
    Status,
    /// Generate preload config from profile data
    AutoConfig,
}

/// Handle 'velo zygote' command (entry point from cli.rs)
pub fn cmd_zygote(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = ZygoteCmd::try_parse_from(&args[1..])?;

    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    match cmd.command {
        ZygoteSubcommand::Start { preload } => cmd_zygote_start(&project_dir, preload),
        ZygoteSubcommand::Stop => {
            cmd_zygote_stop();
            Ok(())
        }
        ZygoteSubcommand::Status => {
            cmd_zygote_status();
            Ok(())
        }
        ZygoteSubcommand::AutoConfig => cmd_zygote_auto_config(),
    }
}

#[cfg(unix)]
fn cmd_zygote_start(project_dir: &Path, preload_arg: Option<String>) -> Result<()> {
    let python_path = python::detect_python(project_dir)?;
    let socket_path = zygote::ipc::default_socket_path();

    if socket_path.exists() {
        println!("⚡ Zygote already running");
        println!("   Socket: {}", socket_path.display());
    } else {
        let mut launcher = ZygoteLauncher::new(socket_path.clone()).with_python(python_path);

        // Parse --preload if provided
        let preload: Vec<&str> = preload_arg
            .as_ref()
            .map(|s| s.split(',').collect())
            .unwrap_or_default();

        let config =
            crate::config::VeloConfig::load_with_overrides(&VeloPaths::pyproject(project_dir));

        println!("🚀 Starting Zygote daemon...");
        match launcher.start(&preload, None, true, &config) {
            Ok(()) => {
                eprintln!(
                    "[ZYGOTE] status=started socket={} preload={:?}",
                    socket_path.display(),
                    preload
                );
                println!("✅ Zygote started");
                println!("   Socket: {}", socket_path.display());
                // Keep launcher alive by forgetting it (daemon mode)
                std::mem::forget(launcher);
            }
            Err(e) => {
                eprintln!("[ZYGOTE] status=failed error={}", e);
                bail!("Failed to start Zygote: {}", e);
            }
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn cmd_zygote_start(_project_dir: &Path, _preload_arg: Option<String>) -> Result<()> {
    bail!("Zygote not supported on this platform");
}

#[cfg(unix)]
fn cmd_zygote_stop() {
    let socket_path = zygote::ipc::default_socket_path();

    if !socket_path.exists() {
        println!("ℹ️  Zygote not running");
    } else {
        println!("🛑 Stopping Zygote...");
        match zygote::ipc::send_command(&socket_path, zygote::ipc::ZygoteCommand::Shutdown, None) {
            Ok(_) => {
                println!("✅ Zygote stopped");
            }
            Err(e) => {
                eprintln!("⚠️  Error stopping Zygote: {}", e);
                zygote::ipc::cleanup_socket(&socket_path);
                println!("   Socket cleaned up");
            }
        }
    }
}

#[cfg(not(unix))]
fn cmd_zygote_stop() {
    eprintln!("ℹ️  Zygote not supported on this platform");
}

#[cfg(unix)]
fn cmd_zygote_status() {
    println!("▸ Zygote Status");
    match crate::zygote::get_status() {
        Ok(crate::zygote::ipc::ZygoteResponse::Status { pid, preload, .. }) => {
            println!("├─ Status: Running ✅ (PID: {})", pid);
            if preload.is_empty() {
                println!("└─ Preload: None");
            } else {
                println!(
                    "└─ Preload: ready ({} modules: {})",
                    preload.len(),
                    preload.join(", ")
                );
            }
        }
        Ok(resp) => {
            println!("├─ Status: Running ✅");
            println!("└─ Details: {:?}", resp);
        }
        Err(e) => {
            println!("└─ Status: Not running or unresponsive (Error: {})", e);
        }
    }
}

#[cfg(not(unix))]
fn cmd_zygote_status() {
    println!("▸ Zygote Status");
    println!("└─ Not supported on this platform");
}

/// Handle 'velo zygote auto-config' command
fn cmd_zygote_auto_config() -> Result<()> {
    use crate::zygote::auto_config::ZygoteConfig;
    use std::fs;

    let project_dir = std::env::current_dir()?;
    let profile_path = VeloPaths::zygote_profile(&project_dir);

    if !profile_path.exists() {
        bail!(
            "No profile data found.\n\n\
             To generate profile data, run:\n  \
             velo run --profile your_script.py\n\n\
             Then run auto-config again."
        );
    }

    let config = ZygoteConfig::from_profile_file(&profile_path)?;

    // Display summary
    println!("{}", config.summary());

    // Update pyproject.toml with [tool.velo] section
    let pyproject_path = VeloPaths::pyproject(&project_dir);

    if pyproject_path.exists() {
        let content = fs::read_to_string(&pyproject_path)?;
        if content.contains("[tool.velo]") {
            eprintln!("⚠️  [tool.velo] section already exists in pyproject.toml");
            eprintln!("   Please update manually with:");
            eprintln!("   preload = {:?}", config.preload);
        } else {
            // Append [tool.velo] section
            let new_content = format!("{}\n{}", content, config.to_toml());
            fs::write(&pyproject_path, new_content)?;
            println!(
                "📝 Updated: {} (added [tool.velo] section)",
                pyproject_path.display()
            );
        }
    } else {
        eprintln!("⚠️  No pyproject.toml found. Add this to your pyproject.toml:");
        println!("{}", config.to_toml());
    }

    if !config.preload.is_empty() {
        println!();
        println!("To start Zygote with these modules:");
        println!("  velo zygote start --preload {}", config.preload.join(","));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_start_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "start"]).unwrap();
        match cmd.command {
            ZygoteSubcommand::Start { preload } => {
                assert!(preload.is_none());
            }
            _ => panic!("Expected Start subcommand"),
        }
    }

    #[test]
    fn test_parse_start_with_preload() {
        let cmd =
            ZygoteCmd::try_parse_from(["zygote", "start", "--preload", "fastapi,uvicorn"]).unwrap();
        match cmd.command {
            ZygoteSubcommand::Start { preload } => {
                assert_eq!(preload.unwrap(), "fastapi,uvicorn");
            }
            _ => panic!("Expected Start subcommand"),
        }
    }

    #[test]
    fn test_parse_stop_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "stop"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::Stop));
    }

    #[test]
    fn test_parse_status_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "status"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::Status));
    }

    #[test]
    fn test_parse_auto_config_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "auto-config"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::AutoConfig));
    }

    #[test]
    fn test_missing_subcommand_error() {
        let result = ZygoteCmd::try_parse_from(["zygote"]);
        assert!(result.is_err());
    }
}
