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
    },
    /// Shutdown the Zygote process
    Shutdown,
}

/// Responses sent from Zygote to Launcher
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ZygoteResponse {
    /// Zygote is ready to accept commands
    Ready,
    /// A worker was successfully forked
    Forked { worker_pid: u32 },
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

    // Send command
    let json =
        serde_json::to_string(&command).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;
    writeln!(stream, "{}", json).map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    stream
        .flush()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // Read response
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    serde_json::from_str(&line).map_err(|e| ZygoteError::ProtocolError(e.to_string()))
}
