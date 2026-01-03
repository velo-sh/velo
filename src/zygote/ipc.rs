//! Zygote IPC - Unix Socket communication between launcher and Zygote process
//!
//! Protocol:
//! ```text
//! Launcher → Zygote:   FORK <script_path> <args>
//!                      SHUTDOWN
//! Zygote → Launcher:   READY
//!                      FORKED <worker_pid>
//!                      ERROR <message>
//! ```

use super::error::{Result, ZygoteError};
use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};

/// Commands sent from Launcher to Zygote
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ZygoteCommand {
    /// Fork a new worker to execute a script
    Fork {
        script_path: PathBuf,
        args: Vec<String>,
        /// Whether to return PID immediately without waiting for completion
        #[serde(default)]
        async_mode: bool,
        /// Optional path for stdout capture (worker writes here)
        #[serde(default)]
        stdout_path: Option<PathBuf>,
        /// Optional path for stderr capture (worker writes here)
        #[serde(default)]
        stderr_path: Option<PathBuf>,
        /// Optional path for exit code capture (worker writes here)
        #[serde(default)]
        exit_code_path: Option<PathBuf>,
        /// Whether to enable Fast Mode (bundle-accelerated imports)
        #[serde(default)]
        fast_mode: bool,
        /// Path to the bundle file for Fast Mode
        #[serde(default)]
        bundle_path: Option<PathBuf>,
        /// Project root directory
        #[serde(default)]
        project_root: Option<PathBuf>,
        /// Max bundle size limit
        #[serde(default)]
        max_bundle_size: Option<u64>,
    },
    /// Shutdown the Zygote process
    Shutdown,
    /// Query Zygote status
    Status,
}

/// Responses sent from Zygote to Launcher
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ZygoteResponse {
    /// Zygote is ready to accept commands
    Ready,
    /// Zygote status information
    Status {
        /// Zygote process ID
        pid: u32,
        /// List of preloaded modules
        preload: Vec<String>,
    },
    /// A worker was successfully forked
    Forked {
        worker_pid: u32,
        /// Exit code (available in sync mode after completion)
        #[serde(default)]
        exit_code: Option<i32>,
    },
    /// An error occurred
    Error { message: String },
}

/// Get the default socket path for Zygote IPC
pub fn default_socket_path() -> PathBuf {
    std::env::temp_dir().join("velo-zygote.sock")
}

/// Create a Unix socket listener at the specified path
pub fn create_listener(socket_path: &Path) -> Result<UnixListener> {
    // Remove existing socket if present
    cleanup_socket(socket_path);

    UnixListener::bind(socket_path).map_err(|e| ZygoteError::SocketError(e.to_string()))
}

/// Clean up the socket file
pub fn cleanup_socket(socket_path: &Path) {
    if socket_path.exists() {
        let _ = std::fs::remove_file(socket_path);
    }
}

/// Accept a command from a client connection
pub fn accept_command(listener: &UnixListener) -> Result<(UnixStream, ZygoteCommand)> {
    let (stream, _) = listener
        .accept()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let mut reader = BufReader::new(
        stream
            .try_clone()
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?,
    );
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let cmd: ZygoteCommand =
        serde_json::from_str(&line).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

    Ok((stream, cmd))
}

/// Send a response back to the launcher
pub fn send_response(stream: &mut UnixStream, response: ZygoteResponse) -> Result<()> {
    let json =
        serde_json::to_string(&response).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;
    writeln!(stream, "{}", json).map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    stream
        .flush()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    Ok(())
}

/// Connect to the Zygote and send a command, returning the response
pub fn send_command(socket_path: &Path, command: ZygoteCommand) -> Result<ZygoteResponse> {
    let mut stream = UnixStream::connect(socket_path)
        .map_err(|e| ZygoteError::ConnectionFailed(e.to_string()))?;

    let stream_clone = stream
        .try_clone()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    let mut reader = BufReader::new(stream_clone);

    // First, receive READY response from Zygote
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let ready_response: ZygoteResponse =
        serde_json::from_str(&line).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

    if !matches!(ready_response, ZygoteResponse::Ready) {
        return Err(ZygoteError::ProtocolError(
            "Expected READY response from Zygote".to_string(),
        ));
    }

    // Send command
    let json =
        serde_json::to_string(&command).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;
    writeln!(stream, "{}", json).map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    stream
        .flush()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // Read response to command
    line.clear();
    reader
        .read_line(&mut line)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    serde_json::from_str(&line).map_err(|e| ZygoteError::ProtocolError(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_serialization() {
        let resp = ZygoteResponse::Status {
            pid: 1234,
            preload: vec!["numpy".to_string(), "pandas".to_string()],
        };
        let json = serde_json::to_string(&resp).unwrap();
        assert!(json.contains("\"type\":\"Status\""));
        assert!(json.contains("\"pid\":1234"));
        assert!(json.contains("\"preload\":[\"numpy\",\"pandas\"]"));

        let decoded: ZygoteResponse = serde_json::from_str(&json).unwrap();
        if let ZygoteResponse::Status { pid, preload } = decoded {
            assert_eq!(pid, 1234);
            assert_eq!(preload, vec!["numpy", "pandas"]);
        } else {
            panic!("Decoded wrong variant");
        }
    }
}
