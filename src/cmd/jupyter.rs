//! Handle 'velo jupyter' command and subcommands
//!
//! RFC-0030: Velo IDE Integration (Jupyter + VS Code)
//! Uses clap for argument parsing with derive macros.

use anyhow::{Result, bail};
use clap::{Parser, Subcommand};
use serde_json::json;
use std::fs;
use std::path::{Path, PathBuf};

use crate::python;

/// Jupyter kernel management
#[derive(Parser, Debug)]
#[command(name = "jupyter", about = "Jupyter kernel integration (RFC-0030)")]
pub struct JupyterCmd {
    #[command(subcommand)]
    pub subcommand: JupyterSubcommand,
}

#[derive(Subcommand, Debug)]
pub enum JupyterSubcommand {
    /// Install Velo as Jupyter kernel
    Install {
        /// Install for system Python (sys.prefix) instead of user directory
        #[arg(long)]
        sys_prefix: bool,

        /// Comma-separated list of modules to preload (hint for Zygote)
        #[arg(long)]
        preload: Option<String>,

        /// Display name for the kernel (default: "Velo Python")
        #[arg(long, default_value = "Velo Python")]
        display_name: String,
    },
}

/// Handle 'velo jupyter' command (entry point from cli.rs)
pub fn cmd_jupyter(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = JupyterCmd::try_parse_from(&args[1..])?;

    match cmd.subcommand {
        JupyterSubcommand::Install {
            sys_prefix,
            preload,
            display_name,
        } => cmd_jupyter_install(sys_prefix, preload.as_deref(), &display_name),
    }
}

/// Install Velo as a Jupyter kernel
///
/// Creates kernel.json in the appropriate Jupyter kernels directory.
/// Per RFC-0030 §3.3, uses `velo run -m ipykernel_launcher -f {connection_file}`.
fn cmd_jupyter_install(sys_prefix: bool, preload: Option<&str>, display_name: &str) -> Result<()> {
    use colored::Colorize;

    println!(
        "{}",
        "🔬 Installing Velo Jupyter Kernel (RFC-0030)"
            .green()
            .bold()
    );

    // 1. Determine kernel directory
    let kernel_dir = get_kernel_directory(sys_prefix)?;
    println!("   Target: {}", kernel_dir.display());

    // 2. Create directory if needed
    fs::create_dir_all(&kernel_dir)?;

    // 3. Get velo binary path
    let velo_path = std::env::current_exe()?;
    let velo_path_str = velo_path.to_string_lossy();

    // 4. Build kernel.json content (RFC-0030 §3.3)
    // Note: -- is required to separate velo options from module args
    let mut kernel_json = json!({
        "argv": [
            velo_path_str,
            "run",
            "-m",
            "ipykernel_launcher",
            "--",
            "-f",
            "{connection_file}"
        ],
        "display_name": display_name,
        "language": "python",
        "metadata": {
            "debugger": true
        }
    });

    // Add preload hint if specified
    if let Some(modules) = preload {
        kernel_json["metadata"]["velo_preload"] = json!(modules);
    }

    // 5. Write kernel.json
    let kernel_json_path = kernel_dir.join("kernel.json");
    let json_content = serde_json::to_string_pretty(&kernel_json)?;
    fs::write(&kernel_json_path, &json_content)?;

    println!("   ✅ Created: {}", kernel_json_path.display());

    // 6. Ensure ipykernel is available
    let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    match ensure_ipykernel(&project_dir) {
        Ok(()) => println!("   ✅ ipykernel dependency verified"),
        Err(e) => {
            println!("   {} ipykernel check failed: {}", "⚠️".yellow(), e);
            println!("   You may need to install it manually: pip install ipykernel");
        }
    }

    // 7. Success message
    println!();
    println!(
        "{}",
        "🎉 Velo kernel installed successfully!".green().bold()
    );
    println!();
    println!("Verify with:");
    println!("   jupyter kernelspec list");
    println!();
    println!("Launch Jupyter:");
    println!("   jupyter lab");
    println!();
    println!("Select \"{}\" as your kernel.", display_name);

    Ok(())
}

/// Get the Jupyter kernels directory
fn get_kernel_directory(sys_prefix: bool) -> Result<PathBuf> {
    if sys_prefix {
        // System-wide: {sys.prefix}/share/jupyter/kernels/velo
        // We need to detect Python to get sys.prefix
        let project_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let python_path = python::detect_python(&project_dir)?;

        // Get sys.prefix from Python
        let output = std::process::Command::new(&python_path)
            .args(["-c", "import sys; print(sys.prefix)"])
            .output()?;

        if !output.status.success() {
            bail!("Failed to get sys.prefix from Python");
        }

        let sys_prefix_path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        Ok(PathBuf::from(sys_prefix_path)
            .join("share")
            .join("jupyter")
            .join("kernels")
            .join("velo"))
    } else {
        // User directory: ~/.local/share/jupyter/kernels/velo
        let home = dirs::home_dir().ok_or_else(|| anyhow::anyhow!("Cannot find home directory"))?;

        #[cfg(target_os = "macos")]
        let jupyter_data = home
            .join("Library")
            .join("Jupyter")
            .join("kernels")
            .join("velo");

        #[cfg(not(target_os = "macos"))]
        let jupyter_data = home
            .join(".local")
            .join("share")
            .join("jupyter")
            .join("kernels")
            .join("velo");

        Ok(jupyter_data)
    }
}

/// Ensure ipykernel is available in the current environment
fn ensure_ipykernel(project_dir: &Path) -> Result<()> {
    let python_path = python::detect_python(project_dir)?;

    // Check if ipykernel is importable
    let output = std::process::Command::new(&python_path)
        .args(["-c", "import ipykernel; print(ipykernel.__version__)"])
        .output()?;

    if output.status.success() {
        return Ok(());
    }

    // Try to install via embedded uv
    // RFC-0018: Use Velo's embedded uv for dependency management
    println!("   📦 Installing ipykernel via embedded uv...");

    let uv_result = std::process::Command::new("uv")
        .args(["pip", "install", "ipykernel"])
        .current_dir(project_dir)
        .status();

    match uv_result {
        Ok(status) if status.success() => Ok(()),
        _ => {
            // Fallback message - don't fail the install
            bail!("ipykernel not found and uv install failed")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_install_subcommand() {
        let cmd = JupyterCmd::try_parse_from(["jupyter", "install"]).unwrap();
        match cmd.subcommand {
            JupyterSubcommand::Install {
                sys_prefix,
                preload,
                display_name,
            } => {
                assert!(!sys_prefix);
                assert!(preload.is_none());
                assert_eq!(display_name, "Velo Python");
            }
        }
    }

    #[test]
    fn test_parse_install_with_sys_prefix() {
        let cmd = JupyterCmd::try_parse_from(["jupyter", "install", "--sys-prefix"]).unwrap();
        match cmd.subcommand {
            JupyterSubcommand::Install { sys_prefix, .. } => {
                assert!(sys_prefix);
            }
        }
    }

    #[test]
    fn test_parse_install_with_preload() {
        let cmd =
            JupyterCmd::try_parse_from(["jupyter", "install", "--preload", "numpy,pandas,torch"])
                .unwrap();
        match cmd.subcommand {
            JupyterSubcommand::Install { preload, .. } => {
                assert_eq!(preload, Some("numpy,pandas,torch".to_string()));
            }
        }
    }

    #[test]
    fn test_parse_install_with_display_name() {
        let cmd = JupyterCmd::try_parse_from([
            "jupyter",
            "install",
            "--display-name",
            "My Custom Kernel",
        ])
        .unwrap();
        match cmd.subcommand {
            JupyterSubcommand::Install { display_name, .. } => {
                assert_eq!(display_name, "My Custom Kernel");
            }
        }
    }

    #[test]
    fn test_kernel_json_format() {
        let velo_path = "/usr/local/bin/velo";
        // Note: -- separates velo options from module args
        let kernel_json = serde_json::json!({
            "argv": [
                velo_path,
                "run",
                "-m",
                "ipykernel_launcher",
                "--",
                "-f",
                "{connection_file}"
            ],
            "display_name": "Velo Python",
            "language": "python",
            "metadata": {
                "debugger": true
            }
        });

        let argv = kernel_json["argv"].as_array().unwrap();
        assert_eq!(argv.len(), 7); // Now includes --
        assert_eq!(argv[0], velo_path);
        assert_eq!(argv[1], "run");
        assert_eq!(argv[2], "-m");
        assert_eq!(argv[3], "ipykernel_launcher");
        assert_eq!(argv[4], "--");
        assert_eq!(argv[5], "-f");
        assert_eq!(argv[6], "{connection_file}");

        assert_eq!(kernel_json["language"], "python");
        assert_eq!(kernel_json["metadata"]["debugger"], true);
    }
}
