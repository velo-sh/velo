//! Handle 'velo serve' command
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::Result;
use clap::Parser;
use std::path::{Path, PathBuf};

use crate::python;
use crate::serve;
use crate::serve::config::{LogFormat, ServeArgs};

/// Serve a Python ASGI/WSGI application
#[derive(Parser, Debug)]
#[command(name = "serve", about = "Serve a Python ASGI/WSGI application")]
pub struct ServeCmd {
    /// Application path (e.g., 'main:app', 'myapp.main:create_app()')
    #[arg(required = true)]
    pub app: String,

    /// Bind host
    #[arg(long, default_value = "127.0.0.1")]
    pub host: String,

    /// Bind port
    #[arg(long, default_value_t = 8000)]
    pub port: u16,

    /// Shorthand for --host and --port (e.g., 0.0.0.0:8080)
    #[arg(long, value_name = "HOST:PORT")]
    pub bind: Option<String>,

    /// Number of workers (default: 1, auto in --prod)
    #[arg(long, default_value_t = 1)]
    pub workers: u32,

    /// Graceful shutdown timeout in seconds
    #[arg(long, default_value_t = 30)]
    pub timeout: u64,

    /// Health check endpoint (e.g., 0.0.0.0:8081)
    #[arg(long, value_name = "ADDR")]
    pub health_bind: Option<String>,

    /// Write PID file for process management
    #[arg(long, value_name = "PATH")]
    pub pid_file: Option<PathBuf>,

    /// Output format: text (default) or json
    #[arg(long, value_name = "FMT", default_value = "text")]
    pub log_format: String,

    /// Enable hot reload (disabled in --prod)
    #[arg(long)]
    pub reload: bool,

    /// Production mode (no reload, auto workers)
    #[arg(long)]
    pub prod: bool,

    /// Disable Zygote pre-warming
    #[arg(long)]
    pub no_zygote: bool,
}

impl ServeCmd {
    /// Convert clap args to ServeArgs
    pub fn to_serve_args(&self) -> Result<ServeArgs> {
        let mut args = ServeArgs::new(self.app.clone());

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
        args.prod = self.prod;
        args.use_zygote = !self.no_zygote;

        // Parse log format
        args.log_format = match self.log_format.as_str() {
            "text" => LogFormat::Text,
            "json" => LogFormat::Json,
            other => anyhow::bail!("unknown log format '{}'. Use 'text' or 'json'", other),
        };

        // Apply prod mode settings
        args.apply_prod_mode();

        // Validate (SEC-P0-001)
        args.validate()?;

        // Validate app format
        if !args.app.contains(':') {
            anyhow::bail!(
                "invalid app format '{}'\nExpected 'module:app' (e.g., 'main:app')",
                args.app
            );
        }

        Ok(args)
    }
}

/// Handle 'velo serve' command (entry point from cli.rs)
pub fn cmd_serve(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo serve" prefix
    let cmd = ServeCmd::try_parse_from(&args[1..])?;

    // Convert to ServeArgs
    let serve_args = cmd.to_serve_args()?;

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Run the server
    serve::run_server(&serve_args, &python_path, &project_dir)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_basic() {
        let cmd = ServeCmd::try_parse_from(["serve", "main:app"]).unwrap();
        assert_eq!(cmd.app, "main:app");
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
    fn test_missing_app_error() {
        let result = ServeCmd::try_parse_from(["serve"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_unknown_option_error() {
        let result = ServeCmd::try_parse_from(["serve", "main:app", "--unknown"]);
        assert!(result.is_err());
    }
}
