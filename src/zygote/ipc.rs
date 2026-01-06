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
/// DEF-61-004: Socket path includes protocol version for upgrade isolation
/// Format: `{socket_dir}/velo-zygote-v{PROTOCOL_VERSION}.sock`
pub fn default_socket_path() -> PathBuf {
    // Audit Remediation: Prioritize explicit socket path from environment (conftest.py support)
    if let Ok(path) = std::env::var("VELO_ZYGOTE_SOCKET") {
        return PathBuf::from(path);
    }

    #[cfg(target_os = "linux")]
    {
        use std::os::unix::ffi::OsStringExt;
        let mut bytes = vec![0u8];
        bytes.extend_from_slice(format!("velo-zygote-v{:02x}", PROTOCOL_VERSION).as_bytes());
        return PathBuf::from(std::ffi::OsString::from_vec(bytes));
    }

    #[cfg(not(target_os = "linux"))]
    get_socket_dir().join(format!("velo-zygote-v{:02x}.sock", PROTOCOL_VERSION))
}

/// Get the user-isolated socket directory
///
/// DEF-61-004: Uses XDG_RUNTIME_DIR or falls back to /tmp/velo-{uid}
/// Directory has 0700 permissions for security
///
/// # Red Line #1: Path Length Circuit Breaker
/// Unix sockets have a 108-character path limit. We use 104 as the threshold
/// to leave margin for the socket filename. If exceeded, fallback to /tmp.
pub fn get_socket_dir() -> PathBuf {
    /// Red Line #1: Path length limit with 4-byte margin
    const SOCKET_PATH_LIMIT: usize = 104;

    let uid = unsafe { libc::getuid() };

    // 1. Try XDG_RUNTIME_DIR (preferred on Linux, usually /run/user/{uid})
    if let Ok(xdg_dir) = std::env::var("XDG_RUNTIME_DIR") {
        let dir = PathBuf::from(xdg_dir).join("velo");
        let test_path = dir.join("velo-zygote-v01.sock");
        if test_path.to_string_lossy().len() <= SOCKET_PATH_LIMIT && ensure_socket_dir(&dir) {
            return dir;
        }
    }

    // 2. Try user-isolated temp directory
    let user_dir = std::env::temp_dir().join(format!("velo-{}", uid));
    let test_path = user_dir.join("velo-zygote-v01.sock");
    // Red Line #1: Check path length BEFORE ensuring directory
    if test_path.to_string_lossy().len() <= SOCKET_PATH_LIMIT && ensure_socket_dir(&user_dir) {
        return user_dir;
    }

    // 3. Fallback to /tmp (for macOS with long $TMPDIR paths)
    // Red Line #1: /tmp fallback when path too long
    if test_path.to_string_lossy().len() > SOCKET_PATH_LIMIT {
        eprintln!(
            "⚠️ $TMPDIR path too long (>{} chars), falling back to /tmp",
            SOCKET_PATH_LIMIT
        );
    }
    let fallback_dir = PathBuf::from("/tmp").join(format!("velo-{}", uid));
    let _ = ensure_socket_dir(&fallback_dir);
    fallback_dir
}

/// Ensure socket directory exists with proper permissions (0700)
///
/// # Red Line #2: Double Permission Verification
/// After setting permissions, we MUST verify the mode is exactly 0700.
/// If umask interferes and permissions are wrong, we log a warning.
fn ensure_socket_dir(dir: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;

    // Create directory if needed
    if !dir.exists() && std::fs::create_dir_all(dir).is_err() {
        return false;
    }

    // Set 0700 permissions (owner only)
    if let Ok(metadata) = dir.metadata() {
        let mut perms = metadata.permissions();
        perms.set_mode(0o700);
        if std::fs::set_permissions(dir, perms.clone()).is_err() {
            return false;
        }

        // Red Line #2: Double verification - confirm mode is 0700
        if let Ok(verify_meta) = dir.metadata() {
            let mode = verify_meta.permissions().mode() & 0o777;
            if mode != 0o700 {
                eprintln!(
                    "⚠️ SECURITY: Socket dir has insecure permissions: {:o} (expected 0700)",
                    mode
                );
                // Continue but warn - umask may have interfered
            }
        }
    }

    true
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
                            eprintln!("🔄 Cleaned stale socket: {}", name);
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

/// Protocol version (ADV-1 + DEF-61-004)
///
/// # Red Line #5: Version Coupling Documentation
/// This constant is used in TWO critical places:
/// 1. **Message framing**: `[Length 4B LE] [Version 1B] [Payload MsgPack]`
/// 2. **Socket path**: `velo-zygote-v{:02x}.sock`
///
/// # Important
/// Incrementing this value creates a NEW socket path, providing automatic
/// isolation from old Zygote processes. Old processes using the previous
/// socket will not interfere with new processes.
///
/// # Version History
/// - 0x00: JSON protocol (v0.6.1 and earlier)
/// - 0x01: MessagePack protocol (v0.6.2+, DEF-61-004)
pub const PROTOCOL_VERSION: u8 = 0x01;

/// Write a MessagePack message with length prefix and version byte
fn write_message<T: Serialize + std::fmt::Debug>(stream: &mut UnixStream, msg: &T) -> Result<()> {
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

/// High-level wrapper for Zygote IPC connection
pub struct ZygoteStream {
    stream: UnixStream,
}

impl ZygoteStream {
    /// Connect to Zygote and verify the initial "Ready" greeting
    pub fn connect(socket_path: &Path) -> Result<Self> {
        let mut stream = UnixStream::connect(socket_path)
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        // 1. Receive mandatory "Ready" greeting
        let ready: ZygoteResponse = read_message(&mut stream)?;
        match ready {
            ZygoteResponse::Ready => Ok(Self { stream }),
            _ => Err(ZygoteError::ProtocolError(
                "Connection greeting failed - expected Ready".to_string(),
            )),
        }
    }

    /// Send a command and wait for the response
    pub fn send_command(&mut self, cmd: &ZygoteCommand) -> Result<ZygoteResponse> {
        write_message(&mut self.stream, cmd)?;
        read_message(&mut self.stream)
    }
}

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
    let mut stream = ZygoteStream::connect(socket_path)?;
    stream.send_command(&command)
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
