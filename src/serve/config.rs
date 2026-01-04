//! Server configuration and validation
//!
//! Centralizes configuration structs and security validation logic.
//! Implements Recommendation #2 (Decoupling CLI & Core Logic).

use anyhow::Result;
use regex::Regex;
use std::path::{Path, PathBuf};

use crate::serve::ServeError;

/// Default port for the server
pub const DEFAULT_PORT: u16 = 8000;

/// Log format for structured output
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum LogFormat {
    #[default]
    Text,
    Json,
}

/// Arguments for `velo serve` command
#[derive(Debug, Clone)]
pub struct ServeArgs {
    /// Application path (e.g., "main:app")
    pub app: String,
    /// Bind host (default: "127.0.0.1")
    pub host: String,
    /// Bind port (default: 8000)
    pub port: u16,
    /// Number of workers (default: 1, auto in --prod mode)
    pub workers: u32,
    /// Enable hot reload (disabled in --prod mode)
    pub reload: bool,
    /// Enable Zygote integration
    pub use_zygote: bool,
    /// Graceful shutdown timeout in seconds (default: 30)
    pub timeout: u64,
    /// Health check endpoint bind address (e.g., "0.0.0.0:8081")
    pub health_bind: Option<String>,
    /// PID file path for process management
    pub pid_file: Option<PathBuf>,
    /// Log format (text or json)
    pub log_format: LogFormat,
    /// Production mode (no reload, auto workers)
    pub prod: bool,
}

impl Default for ServeArgs {
    fn default() -> Self {
        Self {
            app: String::new(),
            host: "127.0.0.1".to_string(),
            port: DEFAULT_PORT,
            workers: 1,
            reload: false,
            use_zygote: true, // Zygote enabled by default
            timeout: 30,      // 30 second graceful shutdown
            health_bind: None,
            pid_file: None,
            log_format: LogFormat::Text,
            prod: false,
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

    /// Apply --prod mode settings
    pub fn apply_prod_mode(&mut self) {
        if self.prod {
            // Disable reload in production
            self.reload = false;
            // Auto-set workers based on CPU count if not explicitly set
            if self.workers == 1 {
                self.workers = std::thread::available_parallelism()
                    .map(|p| p.get() as u32)
                    .unwrap_or(4);
            }
        }
    }

    /// Validate configuration including security checks (SEC-P0-001)
    pub fn validate(&self) -> Result<()> {
        self.validate_app_target()
    }

    /// SEC-P0-001: Validate app target for shell injection prevention
    fn validate_app_target(&self) -> Result<()> {
        // RFC-0010 SEC-P0-001: Strict regex for app format
        let re = Regex::new(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*(\(\))?$").unwrap();

        if !re.is_match(&self.app) {
            // Fallback check for common shell metacharacters
            const FORBIDDEN: &[char] = &[
                '|', '&', ';', '$', '`', '\\', '"', '\'', '<', '>', '\n', '\r', '\0',
            ];

            if self.app.chars().any(|c| FORBIDDEN.contains(&c)) {
                let err = ServeError::ShellMetacharacters {
                    app: self.app.clone(),
                };
                eprintln!("{}", err.format_source_pointed());
                // We use generic error in validate, CLI can choose to exit
                return Err(err.into());
            }

            // Generic invalid format error
            let msg = format!(
                "Invalid app format '{}'. Expected 'module:app' (e.g., 'main:app')",
                self.app
            );
            eprintln!("Error: {}", msg); // Keep stderr for UX
            anyhow::bail!(msg);
        }

        Ok(())
    }
}

/// SEC-P0-002: Path Traversal Protection (RFC §4.10.2)
#[allow(dead_code)]
pub fn validate_scan_path(path: &Path, project_dir: &Path) -> Result<PathBuf> {
    let canonical = path
        .canonicalize()
        .map_err(|e| anyhow::anyhow!("Invalid path: {}", e))?;
    let project = project_dir
        .canonicalize()
        .map_err(|e| anyhow::anyhow!("Invalid project dir: {}", e))?;

    // Must be within project directory
    if !canonical.starts_with(&project) {
        let err = ServeError::PathTraversal {
            path: path.to_path_buf(),
        };
        anyhow::bail!(err);
    }

    Ok(canonical)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_app_target_valid() {
        let args = ServeArgs::new("main:app".to_string());
        assert!(args.validate().is_ok());
    }

    #[test]
    fn test_validate_app_target_invalid() {
        let args = ServeArgs::new("main:app;".to_string());
        assert!(args.validate().is_err());
    }
}
