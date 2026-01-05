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
    /// Dry run mode (log command and exit)
    pub dry_run: bool,
    /// Verbosity level (0-3)
    pub verbose: u8,
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
            dry_run: false,
            verbose: 0,
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
                // RFC-0011 B1: Check K8s cgroup quota first to avoid throttling
                if let Some(quota) = crate::hardware_k8s::get_cgroup_cpu_limit() {
                    self.workers = quota;
                } else {
                    // Fallback to logical cores (physical machine or no quota)
                    self.workers = std::thread::available_parallelism()
                        .map(|p| p.get() as u32)
                        .unwrap_or(4);
                }
            }
        }
    }

    /// Validate all arguments for security and correctness
    pub fn validate(&self) -> Result<()> {
        self.validate_app_target()?;

        // SEC-P0-002: Revalidate PID file path if provided
        if let Some(ref path) = self.pid_file {
            let project_dir =
                std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
            validate_scan_path(path, &project_dir)?;
        }

        self.validate_ranges()?;
        Ok(())
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
                return Err(ServeError::ShellMetacharacters {
                    app: self.app.clone(),
                }
                .into());
            }

            // Generic invalid format error
            return Err(ServeError::InvalidAppFormat {
                app: self.app.clone(),
            }
            .into());
        }

        Ok(())
    }

    /// Validate workers and port ranges
    fn validate_ranges(&self) -> Result<()> {
        if self.workers == 0 {
            return Err(ServeError::InvalidWorkerCount {
                count: self.workers,
            }
            .into());
        }

        if self.port == 0 {
            return Err(ServeError::InvalidPort { port: self.port }.into());
        }

        Ok(())
    }
}

/// SEC-P0-002: Path Traversal Protection (RFC §4.10.2)
pub fn validate_scan_path(path: &Path, project_dir: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        project_dir.join(path)
    };

    let canonical = absolute
        .canonicalize()
        .or_else(|_| {
            // If file doesn't exist, validate parent directory
            if let Some(parent) = absolute.parent() {
                parent
                    .canonicalize()
                    .map(|p| p.join(absolute.file_name().unwrap_or_default()))
            } else {
                Err(std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "Invalid path",
                ))
            }
        })
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
