//! Handle 'velo zygote' command and subcommands

use anyhow::Result;
use std::path::Path;

use crate::python;
use crate::zygote::{self, ZygoteLauncher};

/// Handle 'velo zygote' command
pub fn cmd_zygote(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Usage: velo zygote <start|stop|status>");
        std::process::exit(1);
    }

    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    match args[2].as_str() {
        "start" => cmd_zygote_start(&project_dir, args)?,
        "stop" => cmd_zygote_stop(),
        "status" => cmd_zygote_status(),
        "auto-config" => cmd_zygote_auto_config()?,
        subcmd => {
            eprintln!("Error: unknown zygote subcommand '{}'", subcmd);
            eprintln!("Usage: velo zygote <start|stop|status|auto-config>");
            std::process::exit(1);
        }
    }

    Ok(())
}

#[cfg(unix)]
fn cmd_zygote_start(project_dir: &Path, args: &[String]) -> Result<()> {
    let python_path = python::detect_python(project_dir)?;
    let socket_path = zygote::ipc::default_socket_path();

    if socket_path.exists() {
        println!("⚡ Zygote already running");
        println!("   Socket: {}", socket_path.display());
    } else {
        let mut launcher = ZygoteLauncher::new(socket_path.clone()).with_python(python_path);

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
    Ok(())
}

#[cfg(not(unix))]
fn cmd_zygote_start(_project_dir: &Path, _args: &[String]) -> Result<()> {
    eprintln!("❌ Zygote not supported on this platform");
    std::process::exit(1);
}

#[cfg(unix)]
fn cmd_zygote_stop() {
    let socket_path = zygote::ipc::default_socket_path();

    if !socket_path.exists() {
        println!("ℹ️  Zygote not running");
    } else {
        println!("🛑 Stopping Zygote...");
        match zygote::ipc::send_command(&socket_path, zygote::ipc::ZygoteCommand::Shutdown) {
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
fn cmd_zygote_status() {
    println!("▸ Zygote Status");
    println!("└─ Not supported on this platform");
}

/// Handle 'velo zygote auto-config' command
fn cmd_zygote_auto_config() -> Result<()> {
    use crate::zygote::auto_config::ZygoteConfig;
    use std::fs;

    let profile_path = std::env::temp_dir().join("velo_profile/profile.json");

    if !profile_path.exists() {
        eprintln!("❌ No profile data found.");
        eprintln!();
        eprintln!("To generate profile data, run:");
        eprintln!("  velo run --profile your_script.py");
        eprintln!();
        eprintln!("Then run auto-config again.");
        std::process::exit(1);
    }

    let config = ZygoteConfig::from_profile_file(&profile_path)?;

    // Display summary
    println!("{}", config.summary());

    // Update pyproject.toml with [tool.velo] section
    let pyproject_path = std::env::current_dir()?.join("pyproject.toml");

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
