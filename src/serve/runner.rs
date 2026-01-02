//! Server runner - uvicorn wrapper with Zygote integration
//!
//! Manages uvicorn subprocess with optional Zygote pre-warming.

use anyhow::{Context, Result};
use std::path::Path;
use std::process::{Command, Stdio};

use crate::zygote::ZygoteLauncher;

/// Arguments for `velo serve` command
#[derive(Debug, Clone)]
pub struct ServeArgs {
    /// Application path (e.g., "main:app")
    pub app: String,
    /// Bind host (default: "127.0.0.1")
    pub host: String,
    /// Bind port (default: 8000)
    pub port: u16,
    /// Number of workers (default: 1)
    pub workers: u32,
    /// Enable hot reload
    pub reload: bool,
    /// Enable Zygote integration
    pub use_zygote: bool,
}

impl Default for ServeArgs {
    fn default() -> Self {
        Self {
            app: String::new(),
            host: "127.0.0.1".to_string(),
            port: 8000,
            workers: 1,
            reload: false,
            use_zygote: true, // Zygote enabled by default
        }
    }
}

impl ServeArgs {
    /// Create new ServeArgs with app path
    pub fn new(app: String) -> Self {
        Self {
            app,
            ..Default::default()
        }
    }

    /// Parse app path into module and attribute (e.g., "main:app" -> ("main", "app"))
    pub fn parse_app(&self) -> Result<(&str, &str)> {
        let parts: Vec<&str> = self.app.split(':').collect();
        if parts.len() != 2 {
            anyhow::bail!(
                "Invalid app format '{}'. Expected 'module:app' (e.g., 'main:app')",
                self.app
            );
        }
        Ok((parts[0], parts[1]))
    }
}

/// Run the ASGI/WSGI application via uvicorn
///
/// # Arguments
/// * `args` - Serve command arguments
/// * `python_path` - Path to Python interpreter
/// * `project_dir` - Project directory
#[cfg(unix)]
pub fn run_server(args: &ServeArgs, python_path: &Path, project_dir: &Path) -> Result<()> {
    // Step 1: Validate app format
    let (_module, _attr) = args.parse_app()?;

    // Step 2: Check uvicorn is installed
    if !check_uvicorn_installed(python_path) {
        eprintln!("❌ Missing dependency: uvicorn");
        eprintln!();
        eprintln!("uvicorn is required to run ASGI applications.");
        eprintln!("To fix:");
        eprintln!("    uv add uvicorn");
        std::process::exit(1);
    }

    // Step 3: Start server
    eprintln!("🚀 Starting server...");
    eprintln!("   App:       {}", args.app);
    eprintln!("   Bind:      {}:{}", args.host, args.port);
    eprintln!("   Workers:   {}", args.workers);
    if args.reload {
        eprintln!("   Reload:    enabled");
    }

    // Start Zygote if enabled (without hardcoded framework preload)
    // NOTE: For optimized preloading, use `velo analyze --suggest-preload`
    if args.use_zygote && crate::zygote::is_supported() {
        let socket_path = crate::zygote::ipc::default_socket_path();

        if !socket_path.exists() {
            eprintln!(
                "⚡ Zygote ready (use `velo analyze --suggest-preload` for optimized preloading)"
            );
            let mut launcher =
                ZygoteLauncher::new(socket_path).with_python(python_path.to_path_buf());

            // Start Zygote without preload modules (empty list)
            // Users can configure preload via pyproject.toml [tool.velo] preload
            if let Err(e) = launcher.start(&[]) {
                eprintln!("⚠️  Zygote startup failed: {}", e);
                eprintln!("   Continuing without Zygote optimization");
            } else {
                // Keep Zygote alive
                std::mem::forget(launcher);
            }
        } else {
            eprintln!("⚡ Using existing Zygote");
        }
    }

    // Build uvicorn command
    let mut cmd = Command::new(python_path);
    cmd.arg("-m")
        .arg("uvicorn")
        .arg(&args.app)
        .arg("--host")
        .arg(&args.host)
        .arg("--port")
        .arg(args.port.to_string());

    // Add workers (only if > 1, uvicorn default is 1)
    if args.workers > 1 {
        cmd.arg("--workers").arg(args.workers.to_string());
    }

    // Add reload flag
    if args.reload {
        cmd.arg("--reload");
    }

    // Set working directory
    cmd.current_dir(project_dir);

    // Inherit stdio for interactive use
    cmd.stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    eprintln!();

    // Execute uvicorn
    let status = cmd.status().context("Failed to start uvicorn")?;

    if !status.success() {
        let code = status.code().unwrap_or(1);
        if code == 1 {
            eprintln!();
            eprintln!(
                "💡 Tip: If the app failed to import, check for syntax errors or missing dependencies."
            );
        }
        std::process::exit(code);
    }

    Ok(())
}

fn check_uvicorn_installed(python_path: &Path) -> bool {
    Command::new(python_path)
        .args(["-c", "import uvicorn"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[cfg(not(unix))]
pub fn run_server(args: &ServeArgs, python_path: &Path, project_dir: &Path) -> Result<()> {
    // Windows: run uvicorn without Zygote
    eprintln!("🚀 Starting server (Zygote not supported on Windows)...");
    eprintln!("   App:     {}", args.app);
    eprintln!("   Bind:    {}:{}", args.host, args.port);
    eprintln!("   Workers: {}", args.workers);

    let mut cmd = Command::new(python_path);
    cmd.arg("-m")
        .arg("uvicorn")
        .arg(&args.app)
        .arg("--host")
        .arg(&args.host)
        .arg("--port")
        .arg(args.port.to_string());

    if args.workers > 1 {
        cmd.arg("--workers").arg(args.workers.to_string());
    }

    if args.reload {
        cmd.arg("--reload");
    }

    cmd.current_dir(project_dir)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    let status = cmd
        .status()
        .context("Failed to start uvicorn. Is it installed?")?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_args() {
        let args = ServeArgs::default();
        assert_eq!(args.host, "127.0.0.1");
        assert_eq!(args.port, 8000);
        assert_eq!(args.workers, 1);
        assert!(!args.reload);
        assert!(args.use_zygote);
    }

    #[test]
    fn test_new_with_app() {
        let args = ServeArgs::new("main:app".to_string());
        assert_eq!(args.app, "main:app");
        assert_eq!(args.port, 8000);
    }

    #[test]
    fn test_parse_app_valid() {
        let args = ServeArgs::new("mymodule:application".to_string());
        let (module, attr) = args.parse_app().unwrap();
        assert_eq!(module, "mymodule");
        assert_eq!(attr, "application");
    }

    #[test]
    fn test_parse_app_invalid() {
        let args = ServeArgs::new("invalid_format".to_string());
        assert!(args.parse_app().is_err());
    }

    #[test]
    fn test_parse_app_nested_module() {
        let args = ServeArgs::new("mypackage.main:app".to_string());
        let (module, attr) = args.parse_app().unwrap();
        assert_eq!(module, "mypackage.main");
        assert_eq!(attr, "app");
    }
}
