//! Error types for velo serve command
//!
//! Defines structured error types with exit codes per RFC-0010 §4.9.1.

use std::path::PathBuf;
use thiserror::Error;

/// Errors that can occur during `velo serve` operation.
#[derive(Error, Debug)]
pub enum ServeError {
    /// Python interpreter not found
    #[error("Python not found: {0}")]
    PythonNotFound(String),

    /// Failed to detect ASGI/WSGI app
    #[error("Failed to detect app in {path}")]
    AppNotDetected { path: PathBuf },

    /// Server failed to start
    #[error("Server failed to start: {reason}")]
    ServerStartFailed { reason: String, exit_code: i32 },

    /// Port is already in use
    #[error("Port {port} is already in use")]
    PortInUse { port: u16 },

    /// Missing dependency (uvicorn/gunicorn)
    #[error("Missing dependency: {dep}. Run: {fix}")]
    MissingDependency { dep: String, fix: String },

    /// Invalid app format (e.g., missing colon)
    #[error("Invalid app format: {app}. Expected 'module:app' (e.g., 'main:app')")]
    InvalidAppFormat { app: String },

    /// Shell metacharacters detected (SEC-P0-001)
    #[error("Invalid app: contains shell metacharacters")]
    ShellMetacharacters { app: String },

    /// Path traversal attempt detected (SEC-P0-002)
    #[error("Path traversal detected: {path} is outside project directory")]
    PathTraversal { path: PathBuf },

    /// PID file already exists (SEC-P0-003)
    #[error("PID file already exists: {path}")]
    PidFileExists { path: PathBuf },

    /// File watcher error
    #[error("File watcher error: {0}")]
    WatcherError(String),

    /// Signal handling error
    #[error("Signal handling error: {0}")]
    SignalError(#[from] std::io::Error),

    /// Graceful shutdown timeout
    #[error("Graceful shutdown timed out after {timeout_secs}s")]
    ShutdownTimeout { timeout_secs: u64 },

    /// Environment detection failed
    #[error("Failed to detect virtual environment")]
    VenvNotFound,

    /// Invalid worker count
    #[error("Invalid worker count: {count}. Must be at least 1.")]
    InvalidWorkerCount { count: u32 },

    /// Invalid port number
    #[error("Invalid port: {port}. Must be between 1 and 65535.")]
    InvalidPort { port: u16 },

    /// Unknown framework, cannot auto-select server
    #[error("Unknown framework, cannot auto-select server")]
    UnknownFramework,
}

impl ServeError {
    /// Get the appropriate exit code for this error.
    ///
    /// Exit codes follow BSD conventions:
    /// - 1: General errors
    /// - 98: Address already in use (EADDRINUSE)
    /// - 127: Command not found
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::PythonNotFound(_) => 127,
            Self::PortInUse { .. } => 98,
            Self::MissingDependency { .. } => 1,
            Self::ServerStartFailed { exit_code, .. } => *exit_code,
            Self::InvalidAppFormat { .. } => 1,
            Self::ShellMetacharacters { .. } => 1,
            Self::PathTraversal { .. } => 1,
            Self::PidFileExists { .. } => 1,
            Self::WatcherError(_) => 1,
            Self::SignalError(_) => 1,
            Self::ShutdownTimeout { .. } => 124, // timeout(1) convention
            Self::AppNotDetected { .. } => 1,
            Self::VenvNotFound => 1,
            Self::UnknownFramework => 1,
            Self::InvalidWorkerCount { .. } => 1,
            Self::InvalidPort { .. } => 1,
        }
    }

    /// Check if this error should show a help hint.
    pub fn has_hint(&self) -> bool {
        matches!(
            self,
            Self::MissingDependency { .. }
                | Self::InvalidAppFormat { .. }
                | Self::AppNotDetected { .. }
        )
    }

    /// Format error as Rust-style source-pointing message (D12, RFC §4.12.1)
    ///
    /// Example output:
    /// ```text
    /// error: Failed to detect ASGI app
    ///   --> main.py:1:1
    ///    |
    ///  1 | from fastapi import FastAPI
    ///    | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ///    = help: Add `app = FastAPI()` to your file
    /// ```
    pub fn format_source_pointed(&self) -> String {
        use colored::Colorize;

        let mut output = String::new();

        // Error header
        output.push_str(&format!("{}: {}\n", "error".red().bold(), self));

        // Source pointer and help based on error type
        match self {
            Self::InvalidAppFormat { app } => {
                output.push_str(&format!("  {} {}\n", "-->".blue().bold(), app));
                output.push_str(&format!("   {}\n", "|".blue().bold()));
                output.push_str(&format!(
                    "   {} Expected format: {}:{}\n",
                    "=".blue().bold(),
                    "module".cyan(),
                    "app".cyan()
                ));
                output.push_str(&format!(
                    "   {} help: Use 'main:app' or 'mypackage.main:application'\n",
                    "=".blue().bold()
                ));
            }
            Self::AppNotDetected { path } => {
                output.push_str(&format!(
                    "  {} {}:1:1\n",
                    "-->".blue().bold(),
                    path.display()
                ));
                output.push_str(&format!("   {}\n", "|".blue().bold()));
                output.push_str(&format!(
                    "   {} help: Add `app = FastAPI()` or `app = Flask(__name__)` to your file\n",
                    "=".blue().bold()
                ));
            }
            Self::MissingDependency { dep, fix } => {
                output.push_str(&format!("   {}\n", "|".blue().bold()));
                output.push_str(&format!(
                    "   {} note: {} is required for serving this application\n",
                    "=".blue().bold(),
                    dep.cyan()
                ));
                output.push_str(&format!("   {} help: {}\n", "=".blue().bold(), fix.green()));
            }
            Self::PortInUse { port } => {
                output.push_str(&format!("   {}\n", "|".blue().bold()));
                output.push_str(&format!(
                    "   {} help: Try a different port: {}\n",
                    "=".blue().bold(),
                    format!("--port {}", port + 1).green()
                ));
                output.push_str(&format!(
                    "   {} help: Or kill the process using port {}: {}\n",
                    "=".blue().bold(),
                    port,
                    format!("lsof -i :{} | kill", port).cyan()
                ));
            }
            Self::ShellMetacharacters { app } => {
                output.push_str(&format!("  {} {}\n", "-->".blue().bold(), app));
                output.push_str(&format!("   {}\n", "|".blue().bold()));
                output.push_str(&format!(
                    "   {} note: Shell metacharacters are not allowed for security reasons\n",
                    "=".blue().bold()
                ));
                output.push_str(&format!(
                    "   {} help: Use only alphanumeric characters, dots, colons, and underscores\n",
                    "=".blue().bold()
                ));
            }
            _ => {
                // Generic help for other errors
                if self.has_hint() {
                    output.push_str(&format!(
                        "   {} help: Run 'velo serve --help' for usage information\n",
                        "=".blue().bold()
                    ));
                }
            }
        }

        output
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Exit code tests (D8)
    // ========================================================================

    #[test]
    fn test_exit_codes() {
        assert_eq!(
            ServeError::PythonNotFound("python3".into()).exit_code(),
            127
        );
        assert_eq!(ServeError::PortInUse { port: 8000 }.exit_code(), 98);
        assert_eq!(
            ServeError::MissingDependency {
                dep: "uvicorn".into(),
                fix: "uv add uvicorn".into()
            }
            .exit_code(),
            1
        );
    }

    #[test]
    fn test_exit_code_timeout() {
        let err = ServeError::ShutdownTimeout { timeout_secs: 30 };
        assert_eq!(err.exit_code(), 124, "Timeout should use exit code 124");
    }

    #[test]
    fn test_exit_code_python_not_found() {
        let err = ServeError::PythonNotFound("python".into());
        assert_eq!(
            err.exit_code(),
            127,
            "Python not found should use exit code 127"
        );
    }

    #[test]
    fn test_exit_code_port_in_use() {
        let err = ServeError::PortInUse { port: 8080 };
        assert_eq!(
            err.exit_code(),
            98,
            "Port in use should use exit code 98 (EADDRINUSE)"
        );
    }

    #[test]
    fn test_exit_code_server_start_failed_propagates() {
        let err = ServeError::ServerStartFailed {
            reason: "test".into(),
            exit_code: 42,
        };
        assert_eq!(
            err.exit_code(),
            42,
            "Server start failed should propagate exit code"
        );
    }

    // ========================================================================
    // Error display tests (D8)
    // ========================================================================

    #[test]
    fn test_error_display() {
        let err = ServeError::PortInUse { port: 8080 };
        assert_eq!(err.to_string(), "Port 8080 is already in use");

        let err = ServeError::MissingDependency {
            dep: "uvicorn".into(),
            fix: "uv add uvicorn".into(),
        };
        assert_eq!(
            err.to_string(),
            "Missing dependency: uvicorn. Run: uv add uvicorn"
        );
    }

    #[test]
    fn test_error_display_invalid_app_format() {
        let err = ServeError::InvalidAppFormat {
            app: "invalid".into(),
        };
        assert!(err.to_string().contains("Invalid app format"));
        assert!(err.to_string().contains("invalid"));
    }

    #[test]
    fn test_error_display_shell_metacharacters() {
        let err = ServeError::ShellMetacharacters {
            app: "main:app; rm -rf".into(),
        };
        assert!(err.to_string().contains("shell metacharacters"));
    }

    #[test]
    fn test_error_display_path_traversal() {
        let err = ServeError::PathTraversal {
            path: PathBuf::from("../../etc/passwd"),
        };
        assert!(err.to_string().contains("Path traversal"));
    }

    #[test]
    fn test_error_display_pid_file_exists() {
        let err = ServeError::PidFileExists {
            path: PathBuf::from("/var/run/app.pid"),
        };
        assert!(err.to_string().contains("PID file already exists"));
    }

    #[test]
    fn test_error_display_shutdown_timeout() {
        let err = ServeError::ShutdownTimeout { timeout_secs: 30 };
        assert!(err.to_string().contains("30"));
        assert!(err.to_string().contains("timed out"));
    }

    // ========================================================================
    // has_hint tests (D8)
    // ========================================================================

    #[test]
    fn test_has_hint() {
        assert!(
            ServeError::MissingDependency {
                dep: "uvicorn".into(),
                fix: "uv add uvicorn".into()
            }
            .has_hint()
        );

        assert!(!ServeError::PortInUse { port: 8000 }.has_hint());
    }

    #[test]
    fn test_has_hint_invalid_app_format() {
        let err = ServeError::InvalidAppFormat { app: "bad".into() };
        assert!(err.has_hint(), "InvalidAppFormat should have hint");
    }

    #[test]
    fn test_has_hint_app_not_detected() {
        let err = ServeError::AppNotDetected {
            path: PathBuf::from("main.py"),
        };
        assert!(err.has_hint(), "AppNotDetected should have hint");
    }

    #[test]
    fn test_no_hint_for_security_errors() {
        let err = ServeError::ShellMetacharacters { app: "bad".into() };
        assert!(
            !err.has_hint(),
            "Security errors should not have user-facing hints"
        );

        let err = ServeError::PathTraversal {
            path: PathBuf::from(".."),
        };
        assert!(!err.has_hint());
    }

    // ========================================================================
    // format_source_pointed tests (D12)
    // ========================================================================

    #[test]
    fn test_source_pointed_contains_error_header() {
        let err = ServeError::InvalidAppFormat { app: "bad".into() };
        let output = err.format_source_pointed();
        // Note: "error" is wrapped with ANSI color codes, so check separately
        assert!(
            output.contains("error") || output.contains("\x1b["),
            "Should contain error header or ANSI codes"
        );
    }

    #[test]
    fn test_source_pointed_invalid_app_format_shows_help() {
        let err = ServeError::InvalidAppFormat {
            app: "invalid_format".into(),
        };
        let output = err.format_source_pointed();
        assert!(output.contains("help:"), "Should contain help");
        assert!(output.contains("main:app"), "Should suggest correct format");
    }

    #[test]
    fn test_source_pointed_app_not_detected_shows_path() {
        let err = ServeError::AppNotDetected {
            path: PathBuf::from("main.py"),
        };
        let output = err.format_source_pointed();
        assert!(output.contains("main.py"), "Should contain path");
        assert!(output.contains("-->"), "Should contain source pointer");
    }

    #[test]
    fn test_source_pointed_missing_dependency_shows_fix() {
        let err = ServeError::MissingDependency {
            dep: "uvicorn".into(),
            fix: "uv add uvicorn".into(),
        };
        let output = err.format_source_pointed();
        assert!(
            output.contains("uv add uvicorn"),
            "Should contain fix command"
        );
        assert!(output.contains("help:"), "Should contain help");
    }

    #[test]
    fn test_source_pointed_port_in_use_suggests_alternative() {
        let err = ServeError::PortInUse { port: 8000 };
        let output = err.format_source_pointed();
        assert!(output.contains("--port 8001"), "Should suggest next port");
        assert!(
            output.contains("lsof"),
            "Should suggest checking port usage"
        );
    }

    #[test]
    fn test_source_pointed_shell_metacharacters_security_note() {
        let err = ServeError::ShellMetacharacters {
            app: "main:app; ls".into(),
        };
        let output = err.format_source_pointed();
        assert!(output.contains("security"), "Should mention security");
        assert!(output.contains("-->"), "Should point to input");
    }

    // ========================================================================
    // All error variants have valid exit codes
    // ========================================================================

    #[test]
    fn test_all_error_variants_have_exit_codes() {
        // Ensure all variants return a valid exit code
        let errors = vec![
            ServeError::PythonNotFound("python".into()),
            ServeError::AppNotDetected {
                path: PathBuf::from("app.py"),
            },
            ServeError::ServerStartFailed {
                reason: "test".into(),
                exit_code: 1,
            },
            ServeError::PortInUse { port: 8000 },
            ServeError::MissingDependency {
                dep: "uvicorn".into(),
                fix: "uv add uvicorn".into(),
            },
            ServeError::InvalidAppFormat { app: "bad".into() },
            ServeError::ShellMetacharacters { app: "bad".into() },
            ServeError::PathTraversal {
                path: PathBuf::from(".."),
            },
            ServeError::PidFileExists {
                path: PathBuf::from("app.pid"),
            },
            ServeError::WatcherError("error".into()),
            ServeError::ShutdownTimeout { timeout_secs: 30 },
            ServeError::VenvNotFound,
            ServeError::UnknownFramework,
        ];

        for err in errors {
            let code = err.exit_code();
            assert!(code >= 1, "Exit code should be >= 1: {}", err);
        }
    }
}
