//! Zygote IPC - Unix Socket communication between launcher and Zygote process
//!
//! Protocol (MessagePack with length prefix):
//! ```text
//! ┌──────────────┬───────────────────────┐
//! │ Length (4B)  │ MessagePack Payload   │
//! │ Little-endian│                       │
//! └──────────────┴───────────────────────┘
//! ```
//!
//! Message types:
//! - Launcher → Zygote:   Fork, Shutdown, Status
//! - Zygote → Launcher:   Ready, Ack, Status, Forked, Error

use super::error::{Result, ZygoteError};
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};

/// Maximum message size (1MB) - prevents DoS via oversized messages
const MAX_MESSAGE_SIZE: usize = 1024 * 1024;

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
    /// Generic acknowledgment of command receipt
    Ack,
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

// ============================================================================
// MessagePack serialization helpers (length-prefix + version framing)
// ============================================================================

/// Protocol version (ADV-1)
/// Layout: [Length 4B LE] [Version 1B] [Payload MsgPack]
const PROTOCOL_VERSION: u8 = 0x01;

/// Write a MessagePack message with length prefix and version byte
fn write_message<T: Serialize + std::fmt::Debug>(stream: &mut UnixStream, msg: &T) -> Result<()> {
    let payload = rmp_serde::to_vec(msg).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

    // Security: Check message size
    if payload.len() > MAX_MESSAGE_SIZE {
        return Err(ZygoteError::ProtocolError(format!(
            "Message too large: {} bytes (max {})",
            payload.len(),
            MAX_MESSAGE_SIZE
        )));
    }

    // ADV-2: TRACE logging (decode to readable format)
    #[cfg(debug_assertions)]
    eprintln!("[IPC SEND] {:?}", msg);

    // Write 4-byte length prefix (little-endian) - includes version + payload
    let total_len = 1 + payload.len(); // version byte + payload
    let len_bytes = (total_len as u32).to_le_bytes();
    stream
        .write_all(&len_bytes)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // Write version byte (ADV-1)
    stream
        .write_all(&[PROTOCOL_VERSION])
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // Write payload
    stream
        .write_all(&payload)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    stream
        .flush()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    Ok(())
}

/// Read a MessagePack message with length prefix and version byte
fn read_message<T: for<'de> Deserialize<'de> + std::fmt::Debug>(
    stream: &mut UnixStream,
) -> Result<T> {
    // Read 4-byte length prefix (includes version + payload)
    let mut len_buf = [0u8; 4];
    stream
        .read_exact(&mut len_buf)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let total_len = u32::from_le_bytes(len_buf) as usize;

    // Security: Check message size
    if total_len > MAX_MESSAGE_SIZE {
        return Err(ZygoteError::ProtocolError(format!(
            "Message too large: {} bytes (max {})",
            total_len, MAX_MESSAGE_SIZE
        )));
    }

    // Need at least version byte
    if total_len < 1 {
        return Err(ZygoteError::ProtocolError(
            "Message too small to contain version byte".to_string(),
        ));
    }

    // Read version byte (ADV-1)
    let mut version_buf = [0u8; 1];
    stream
        .read_exact(&mut version_buf)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let version = version_buf[0];
    if version != PROTOCOL_VERSION {
        return Err(ZygoteError::ProtocolError(format!(
            "Protocol version mismatch: got {}, expected {}",
            version, PROTOCOL_VERSION
        )));
    }

    // Read payload (total_len - 1 for version byte)
    let payload_len = total_len - 1;
    let mut buf = vec![0u8; payload_len];
    stream
        .read_exact(&mut buf)
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // Deserialize
    let msg: T =
        rmp_serde::from_slice(&buf).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

    // ADV-2: TRACE logging (decode to readable format)
    #[cfg(debug_assertions)]
    eprintln!("[IPC RECV] {:?}", msg);

    Ok(msg)
}

// ============================================================================
// Public API
// ============================================================================

/// Accept a command from a client connection
pub fn accept_command(listener: &UnixListener) -> Result<(UnixStream, ZygoteCommand)> {
    let (mut stream, _) = listener
        .accept()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    let cmd: ZygoteCommand = read_message(&mut stream)?;

    Ok((stream, cmd))
}

/// Send a response back to the launcher
pub fn send_response(stream: &mut UnixStream, response: ZygoteResponse) -> Result<()> {
    write_message(stream, &response)
}

/// Connect to the Zygote and send a command, returning the response
pub fn send_command(socket_path: &Path, command: ZygoteCommand) -> Result<ZygoteResponse> {
    let mut stream = UnixStream::connect(socket_path)
        .map_err(|e| ZygoteError::ConnectionFailed(e.to_string()))?;

    // First, receive READY response from Zygote
    let ready_response: ZygoteResponse = read_message(&mut stream)?;

    if !matches!(ready_response, ZygoteResponse::Ready) {
        return Err(ZygoteError::ProtocolError(
            "Expected READY response from Zygote".to_string(),
        ));
    }

    // Send command
    write_message(&mut stream, &command)?;

    // Read response to command
    read_message(&mut stream)
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

        // Test MessagePack roundtrip
        let bytes = rmp_serde::to_vec(&resp).unwrap();
        let decoded: ZygoteResponse = rmp_serde::from_slice(&bytes).unwrap();

        if let ZygoteResponse::Status { pid, preload } = decoded {
            assert_eq!(pid, 1234);
            assert_eq!(preload, vec!["numpy", "pandas"]);
        } else {
            panic!("Decoded wrong variant");
        }
    }

    #[test]
    fn test_fork_command_serialization() {
        let cmd = ZygoteCommand::Fork {
            script_path: PathBuf::from("/tmp/test.py"),
            args: vec!["--flag".to_string()],
            async_mode: true,
            stdout_path: None,
            stderr_path: None,
            exit_code_path: None,
            fast_mode: false,
            bundle_path: None,
            project_root: None,
            max_bundle_size: None,
        };

        let bytes = rmp_serde::to_vec(&cmd).unwrap();
        let decoded: ZygoteCommand = rmp_serde::from_slice(&bytes).unwrap();

        if let ZygoteCommand::Fork {
            script_path,
            async_mode,
            ..
        } = decoded
        {
            assert_eq!(script_path, PathBuf::from("/tmp/test.py"));
            assert!(async_mode);
        } else {
            panic!("Decoded wrong variant");
        }
    }

    #[test]
    fn test_message_size_smaller_than_json() {
        let cmd = ZygoteCommand::Fork {
            script_path: PathBuf::from("/tmp/test.py"),
            args: vec!["arg1".to_string(), "arg2".to_string()],
            async_mode: true,
            stdout_path: Some(PathBuf::from("/tmp/out.txt")),
            stderr_path: Some(PathBuf::from("/tmp/err.txt")),
            exit_code_path: Some(PathBuf::from("/tmp/exit.txt")),
            fast_mode: true,
            bundle_path: Some(PathBuf::from("/tmp/bundle.veloc")),
            project_root: Some(PathBuf::from("/home/user/project")),
            max_bundle_size: Some(1024 * 1024),
        };

        let msgpack_bytes = rmp_serde::to_vec(&cmd).unwrap();
        let json_bytes = serde_json::to_vec(&cmd).unwrap();

        // MessagePack should be smaller
        assert!(
            msgpack_bytes.len() < json_bytes.len(),
            "MessagePack {} bytes should be smaller than JSON {} bytes",
            msgpack_bytes.len(),
            json_bytes.len()
        );
    }
}
