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
use std::time::{Duration, Instant};

pub use crate::common::constants::{MAX_MESSAGE_SIZE, PROTOCOL_VERSION};

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
        /// Environment variables to inject into the worker
        #[serde(default)]
        env: Box<std::collections::HashMap<String, String>>,
    },
    /// Shutdown the Zygote process
    Shutdown,
    /// Query Zygote status
    Status,
    /// Wait for a worker to exit
    WaitWorker {
        worker_pid: u32,
        #[serde(default)]
        timeout_secs: Option<u64>,
    },
    /// Send signal to a worker
    SignalWorker { worker_pid: u32, signal: i32 },
    /// Query worker status
    WorkerStatus { worker_pid: u32 },
    /// Capability handshake
    Handshake {
        version: u8,
        capabilities: Vec<String>,
    },
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
        /// Preload state (e.g., "READY", "LOADING")
        #[serde(default)]
        state: String,
    },
    /// A worker was successfully forked
    Forked {
        worker_pid: u32,
        /// Exit code (available in sync mode after completion)
        #[serde(default)]
        exit_code: Option<i32>,
    },
    /// Worker exited with code
    WorkerExited { worker_pid: u32, exit_code: i32 },
    /// Worker status info
    WorkerInfo {
        worker_pid: u32,
        is_running: bool,
        uptime_secs: u64,
    },
    /// An error occurred
    Error { message: String },
    /// Handshake response
    Handshake {
        version: u8,
        capabilities: Vec<String>,
    },
}

/// Get the default socket path for Zygote IPC
///
/// Delegates to `common::paths` for canonical resolution (RFC-0012).
pub fn default_socket_path() -> PathBuf {
    crate::common::paths::get_socket_path()
}

/// Get the user-isolated socket directory
///
/// Delegates to `common::paths` (RFC-0012).
pub fn get_socket_dir() -> PathBuf {
    crate::common::paths::get_socket_dir()
}

/// Check if a socket is alive (responds to connection attempt)
///
/// # Side Effect (Red Line #4 Documentation)
/// This function creates an actual TCP connection to the socket.
/// If the socket is alive, the server will `accept()` this probe connection,
/// then immediately see EOF when we disconnect.
///
/// This is acceptable because:
/// - Probe happens during startup before Zygote is running
/// - Used only in `cleanup_stale_sockets()` to detect dead sockets
/// - Connection is immediately dropped after probe
pub fn is_socket_alive(socket_path: &Path) -> bool {
    // RFC-0011 D.1: Abstract sockets don't "exist" on filesystem
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::ffi::OsStrExt;
        let bytes = socket_path.as_os_str().as_bytes();
        if !bytes.is_empty() && bytes[0] == 0 {
            // Abstract socket, skip exists() check and use connect directly
            return UnixStream::connect(socket_path).is_ok();
        }
    }

    if !socket_path.exists() {
        return false;
    }

    // Try to connect - if it succeeds, socket is alive
    UnixStream::connect(socket_path).is_ok()
}

/// Clean up stale sockets from previous versions
///
/// DEF-61-004: On startup, remove sockets that are not alive
/// This handles upgrade scenarios where old Zygote processes died
///
/// # Red Line #3: Atomic Cleanup Semantics
/// - MUST ignore `NotFound` errors (prevents race conditions)
/// - MUST alert on `PermissionDenied` (indicates misconfigured residual files)
pub fn cleanup_stale_sockets() {
    let socket_dir = get_socket_dir();

    if !socket_dir.exists() {
        return;
    }

    // Find all velo-zygote-*.sock files
    if let Ok(entries) = std::fs::read_dir(&socket_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                // Only clean up velo-zygote sockets that are not alive
                if name.starts_with("velo-zygote-")
                    && name.ends_with(".sock")
                    && !is_socket_alive(&path)
                {
                    // Red Line #3: Atomic cleanup with proper error handling
                    match std::fs::remove_file(&path) {
                        Ok(_) => {
                            // println!("🔄 Cleaned stale socket: {}", name);
                        }
                        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                            // Ignore - socket already removed (race condition)
                        }
                        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                            // Red Line #3: Alert on permission denied
                            eprintln!(
                                "⚠️ SECURITY: Cannot remove socket (permission denied): {}",
                                name
                            );
                        }
                        Err(e) => {
                            eprintln!("⚠️ Failed to remove stale socket {}: {}", name, e);
                        }
                    }
                }
            }
        }
    }
}

/// Create a Unix socket listener at the specified path
pub fn create_listener(socket_path: &Path) -> Result<UnixListener> {
    // Remove existing socket if present
    cleanup_socket(socket_path);

    UnixListener::bind(socket_path).map_err(|e| ZygoteError::SocketError(e.to_string()))
}

/// Clean up the socket file
pub fn cleanup_socket(socket_path: &Path) {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::ffi::OsStrExt;
        let bytes = socket_path.as_os_str().as_bytes();
        if !bytes.is_empty() && bytes[0] == 0 {
            return; // Abstract socket, nothing to cleanup
        }
    }

    if socket_path.exists() {
        let _ = std::fs::remove_file(socket_path);
    }
}

// ============================================================================
// MessagePack serialization helpers (length-prefix + version framing)
// ============================================================================

// Protocol version (ADV-1 + DEF-61-004) - Now using SSOT from config/constants.toml

/// Helper for enforcing a wall-clock deadline across multiple IPC operations
struct Deadline {
    end: Instant,
}

impl Deadline {
    fn new(timeout: Duration) -> Self {
        Self {
            end: Instant::now() + timeout,
        }
    }

    fn remaining(&self) -> Result<Duration> {
        let now = Instant::now();
        if now >= self.end {
            return Err(ZygoteError::ConnectionFailed(
                "Kinetic handshake budget exceeded (10ms wall-clock deadline)".to_string(),
            ));
        }
        Ok(self.end - now)
    }

    /// Apply remaining time as socket timeout
    fn apply(&self, stream: &UnixStream) -> Result<()> {
        let timeout = self.remaining()?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
        Ok(())
    }
}

/// Write a MessagePack message with length prefix and version byte
fn write_message<T: Serialize + std::fmt::Debug>(
    stream: &mut UnixStream,
    msg: &T,
    deadline: Option<&Deadline>,
) -> Result<()> {
    if let Some(d) = deadline {
        d.apply(stream)?;
    }
    let mut buf = Vec::new();
    let mut ser = rmp_serde::Serializer::new(&mut buf).with_struct_map();
    msg.serialize(&mut ser)
        .map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

    let payload = buf;

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
    {
        // println!("[IPC SEND] {:?}", msg);
    }

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
    deadline: Option<&Deadline>,
) -> Result<T> {
    if let Some(d) = deadline {
        d.apply(stream)?;
    }
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
            "Protocol version mismatch: got 0x{:02x}, expected 0x{:02x}. Is one side outdated?",
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
    {
        // println!("[IPC RECV] {:?}", msg);
    }

    Ok(msg)
}

/// High-level wrapper for Zygote IPC connection
pub struct ZygoteStream {
    stream: UnixStream,
    deadline: Deadline,
}

impl ZygoteStream {
    /// Connect to Zygote and verify the initial "Ready" greeting
    ///
    /// RFC-0013: Enforces a 10ms wall-clock timeout for the entire handshake.
    pub fn connect(socket_path: &Path) -> Result<Self> {
        // DEF-62-002: Increased to 2000ms (2s) to tolerate GIL contention during Shadow Preloading.
        // Idle Zygote responds in <1ms. Busy Zygote (loading pandas) needs patience.
        let deadline = Deadline::new(Duration::from_millis(2000));

        let stream = UnixStream::connect(socket_path).map_err(|e| {
            ZygoteError::ConnectionFailed(format!("Failed to connect to Zygote: {}", e))
        })?;

        // 0. Verify server identity (RFC §3.7 Mutual Auth)
        #[cfg(target_os = "linux")]
        verify_peer_credentials(&stream)?;

        let mut zygote_stream = Self { stream, deadline };

        // 1. Receive mandatory "Ready" greeting
        let ready: ZygoteResponse =
            read_message(&mut zygote_stream.stream, Some(&zygote_stream.deadline))?;
        match ready {
            ZygoteResponse::Ready => Ok(zygote_stream),
            _ => Err(ZygoteError::ProtocolError(
                "Connection greeting failed - expected Ready".to_string(),
            )),
        }
    }

    /// Send a command and wait for the response
    pub fn send_command(&mut self, cmd: &ZygoteCommand) -> Result<ZygoteResponse> {
        write_message(&mut self.stream, cmd, Some(&self.deadline))?;
        read_message(&mut self.stream, Some(&self.deadline))
    }
}

/// Accept a command from a client connection
pub fn accept_command(listener: &UnixListener) -> Result<(UnixStream, ZygoteCommand)> {
    let (mut stream, _) = listener
        .accept()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // 0. Verify client identity (RFC §3.7)
    #[cfg(target_os = "linux")]
    verify_peer_credentials(&stream)?;

    let cmd: ZygoteCommand = read_message(&mut stream, None)?;

    Ok((stream, cmd))
}

/// Send a response back to the launcher
pub fn send_response(stream: &mut UnixStream, response: ZygoteResponse) -> Result<()> {
    write_message(stream, &response, None)
}

/// Connect to the Zygote and send a command, returning the response
pub fn send_command(socket_path: &Path, command: ZygoteCommand) -> Result<ZygoteResponse> {
    let mut stream = ZygoteStream::connect(socket_path)?;
    stream.send_command(&command)
}

/// Verify that the peer is owned by the same user (RFC §3.7)
///
/// This is CRITICAL for Abstract Namespace Sockets which rely entirely
/// on peer credentials for security, having no filesystem permissions.
#[cfg(target_os = "linux")]
fn verify_peer_credentials(stream: &UnixStream) -> Result<()> {
    use std::os::unix::io::AsRawFd;

    let fd = stream.as_raw_fd();
    let ucred = unsafe {
        let mut ucred: libc::ucred = std::mem::zeroed();
        let mut len = std::mem::size_of::<libc::ucred>() as u32;
        if libc::getsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            &mut ucred as *mut _ as *mut libc::c_void,
            &mut len,
        ) != 0
        {
            return Err(ZygoteError::SecurityViolation(
                "Failed to get peer credentials".to_string(),
            ));
        }
        ucred
    };

    let current_uid = unsafe { libc::getuid() };
    if ucred.uid != current_uid {
        return Err(ZygoteError::SecurityViolation(format!(
            "Peer UID mismatch: expected {}, got {}",
            current_uid, ucred.uid
        )));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_serialization() {
        let resp = ZygoteResponse::Status {
            pid: 1234,
            preload: vec!["numpy".to_string(), "pandas".to_string()],
            state: "READY".to_string(),
        };

        // Test MessagePack roundtrip
        let bytes = rmp_serde::to_vec(&resp).unwrap();
        let decoded: ZygoteResponse = rmp_serde::from_slice(&bytes).unwrap();

        if let ZygoteResponse::Status {
            pid,
            preload,
            state,
        } = decoded
        {
            assert_eq!(pid, 1234);
            assert_eq!(preload, vec!["numpy", "pandas"]);
            assert_eq!(state, "READY");
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
            env: Box::new(std::collections::HashMap::new()),
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
            env: Box::new(std::collections::HashMap::new()),
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

    #[test]
    fn test_read_message_oversized() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;

        let (mut reader, mut writer) = UnixStream::pair().unwrap();

        // Send a message that claims to be huge
        let huge_len = (MAX_MESSAGE_SIZE + 1) as u32;
        writer.write_all(&huge_len.to_le_bytes()).unwrap();

        let res: Result<ZygoteResponse> = read_message(&mut reader, None);
        assert!(res.is_err());
        let err = res.unwrap_err().to_string();
        assert!(err.contains("Message too large"));
    }

    #[test]
    fn test_read_message_version_mismatch() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;

        let (mut reader, mut writer) = UnixStream::pair().unwrap();

        let total_len = 1u32;
        writer.write_all(&total_len.to_le_bytes()).unwrap();
        writer.write_all(&[0xFF]).unwrap(); // Wrong version

        let res: Result<ZygoteResponse> = read_message(&mut reader, None);
        assert!(res.is_err());
        let err = res.unwrap_err().to_string();
        assert!(err.contains("Protocol version mismatch"));
    }
}
