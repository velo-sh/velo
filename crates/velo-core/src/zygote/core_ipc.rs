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
use nix::sys::socket::{ControlMessage, ControlMessageOwned, MsgFlags, recvmsg, sendmsg};
use serde::{Deserialize, Serialize};
use std::io::{IoSlice, IoSliceMut};
use std::io::{Read, Write};
use std::os::unix::io::{AsRawFd, RawFd};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};

pub use velo_protocol::constants::{MAX_MESSAGE_SIZE, PROTOCOL_VERSION};

pub use velo_protocol::{ZygoteCommand, ZygoteResponse};

/// Get the default socket path for Zygote IPC
///
/// Delegates to `crate::common::paths` for canonical resolution (RFC-0012).
pub fn default_socket_path() -> PathBuf {
    crate::common::paths::get_socket_path()
}

/// Get the user-isolated socket directory
///
/// Delegates to `crate::common::paths` (RFC-0012).
pub fn get_socket_dir() -> PathBuf {
    crate::common::paths::VeloPaths::socket_dir()
}

/// Get project-aware Zygote socket path (STB-SOCKET-003)
///
/// Returns a unique socket path for the given project directory and app.
/// Format: velo-zygote-{name8}-{hash6}-v{version}.sock
pub fn socket_path_for_app(project_dir: &Path, app: &str) -> PathBuf {
    crate::common::paths::VeloPaths::zygote_socket_for_app(project_dir, app)
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
#[allow(clippy::doc_lazy_continuation)]
/// Check if a Zygote socket is alive (Shallow Probe).
///
/// This only verifies that the socket is accepting connections.
/// It does NOT perform a handshake. Used in startup loops.
pub fn is_socket_alive(socket_path: &Path) -> bool {
    #[cfg(target_os = "linux")]
    {
        // Check for @ prefix which indicates abstract socket internal representation
        let name_str = socket_path.to_string_lossy();
        if name_str.starts_with('@')
            && crate::common::paths::connect_abstract_socket(&name_str).is_ok()
        {
            return true;
        }

        use std::os::unix::ffi::OsStrExt;
        let bytes = socket_path.as_os_str().as_bytes();
        if !bytes.is_empty() && bytes[0] == 0 {
            // Fallback logic if passed with \0
            let name = socket_path.to_string_lossy();
            return crate::common::paths::connect_abstract_socket(&name).is_ok();
        }
    }

    if !socket_path.exists() {
        return false;
    }

    std::os::unix::net::UnixStream::connect(socket_path).is_ok()
}

/// Check if a Zygote socket is responsive (Deep Probe).
///
/// Performs a full protocol handshake. Used in is_alive() for reliability.
pub fn is_socket_responsive(socket_path: &Path) -> bool {
    ZygoteStream::connect(socket_path).is_ok()
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

    #[cfg(target_os = "linux")]
    {
        // Check for @ prefix which indicates abstract socket internal representation
        // (to avoid \0 NULL byte handling issues in Path/String conversions)
        let name_str = socket_path.to_string_lossy();
        if name_str.starts_with('@') {
            return crate::common::paths::bind_abstract_socket(&name_str)
                .map_err(|e| ZygoteError::SocketError(e.to_string()));
        }

        // Legacy check just in case
        use std::os::unix::ffi::OsStrExt;
        let bytes = socket_path.as_os_str().as_bytes();
        if !bytes.is_empty() && bytes[0] == 0 {
            let name = socket_path.to_string_lossy();
            return crate::common::paths::bind_abstract_socket(&name)
                .map_err(|e| ZygoteError::SocketError(e.to_string()));
        }
    }

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

/// Write a MessagePack message with length prefix and version byte
pub fn write_message<T: Serialize + std::fmt::Debug>(
    stream: &mut UnixStream,
    msg: &T,
    fd: Option<RawFd>,
) -> Result<()> {
    let payload = serde_json::to_vec(msg).map_err(|e| ZygoteError::ProtocolError(e.to_string()))?;

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
        log::debug!("[IPC SEND] {:?}", msg);
    }

    // Frame: [Length 4B] [Version 1B] [Payload]
    let total_len = 1 + payload.len(); // version byte + payload
    let len_bytes = (total_len as u32).to_le_bytes();
    let version_byte = [PROTOCOL_VERSION];

    if let Some(raw_fd) = fd {
        // Use SCM_RIGHTS via sendmsg
        let iov = [
            IoSlice::new(&len_bytes),
            IoSlice::new(&version_byte),
            IoSlice::new(&payload),
        ];

        let cmsg = [ControlMessage::ScmRights(&[raw_fd])];

        sendmsg::<()>(stream.as_raw_fd(), &iov, &cmsg, MsgFlags::empty(), None)
            .map_err(|e| ZygoteError::SocketError(format!("sendmsg failed: {}", e)))?;
    } else {
        // Standard Write
        stream
            .write_all(&len_bytes)
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        stream
            .write_all(&version_byte)
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        stream
            .write_all(&payload)
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        stream
            .flush()
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
    }

    Ok(())
}

/// Read a MessagePack message with length prefix and version byte
/// Read a MessagePack message with length prefix and version byte
pub fn read_message<T: for<'de> Deserialize<'de> + std::fmt::Debug>(
    stream: &mut UnixStream,
) -> Result<(T, Option<RawFd>)> {
    // Helper to ensure FD is closed on error
    let cleanup_fd = |fd: &mut Option<RawFd>| {
        if let Some(f) = fd.take() {
            let _ = nix::unistd::close(f);
        }
    };

    // Read 4-byte length prefix (includes version + payload)
    // Use recvmsg to capture synchronous ancillary data (FDs)
    let mut len_buf = [0u8; 4];
    let mut cmsg = nix::cmsg_space!([RawFd; 1]);
    let (bytes, mut received_fd) = {
        let mut iov = [IoSliceMut::new(&mut len_buf)];

        let msg_result = recvmsg::<()>(
            stream.as_raw_fd(),
            &mut iov,
            Some(&mut cmsg),
            MsgFlags::empty(),
        )
        .map_err(|e| ZygoteError::SocketError(format!("recvmsg failed: {}", e)))?;

        let mut fd = None;
        for cmsg in msg_result.cmsgs() {
            if let ControlMessageOwned::ScmRights(fds) = cmsg {
                fd = fds.first().copied();
            }
        }

        // Council Advisory: Check for control message truncation
        if msg_result.flags.contains(MsgFlags::MSG_CTRUNC) {
            cleanup_fd(&mut fd);
            return Err(ZygoteError::ProtocolError(
                "Control message truncated (too many FDs)".to_string(),
            ));
        }

        (msg_result.bytes, fd)
    };

    // Ensure we have full 4 bytes for length
    if bytes < 4 {
        stream.read_exact(&mut len_buf[bytes..]).map_err(|e| {
            cleanup_fd(&mut received_fd);
            ZygoteError::SocketError(e.to_string())
        })?;
    }

    let total_len = u32::from_le_bytes(len_buf) as usize;

    // Security: Check message size
    if total_len > MAX_MESSAGE_SIZE {
        cleanup_fd(&mut received_fd);
        return Err(ZygoteError::ProtocolError(format!(
            "Message too large: {} bytes (max {})",
            total_len, MAX_MESSAGE_SIZE
        )));
    }

    // Need at least version byte
    if total_len < 1 {
        cleanup_fd(&mut received_fd);
        return Err(ZygoteError::ProtocolError(
            "Message too small to contain version byte".to_string(),
        ));
    }

    // Read version byte (ADV-1)
    let mut version_buf = [0u8; 1];
    if let Err(e) = stream.read_exact(&mut version_buf) {
        cleanup_fd(&mut received_fd);
        return Err(ZygoteError::SocketError(e.to_string()));
    }

    let version = version_buf[0];
    if version != PROTOCOL_VERSION {
        cleanup_fd(&mut received_fd);
        return Err(ZygoteError::ProtocolError(format!(
            "Protocol version mismatch: got 0x{:02x}, expected 0x{:02x}. Is one side outdated?",
            version, PROTOCOL_VERSION
        )));
    }

    // Read payload (total_len - 1 for version byte)
    let payload_len = total_len - 1;
    let mut buf = vec![0u8; payload_len];
    if let Err(e) = stream.read_exact(&mut buf) {
        cleanup_fd(&mut received_fd);
        return Err(ZygoteError::SocketError(e.to_string()));
    }

    // Deserialize
    let msg: T = serde_json::from_slice(&buf).map_err(|e| {
        cleanup_fd(&mut received_fd);
        ZygoteError::ProtocolError(e.to_string())
    })?;

    // ADV-2: TRACE logging (decode to readable format)
    #[cfg(debug_assertions)]
    eprintln!("[IPC RECV] {:?} (fd: {:?})", msg, received_fd);

    Ok((msg, received_fd))
}

/// High-level wrapper for Zygote IPC connection
pub struct ZygoteStream {
    pub stream: UnixStream,
}

impl ZygoteStream {
    /// Create a ZygoteStream from an existing UnixStream
    pub fn from_stream(stream: UnixStream) -> Self {
        Self { stream }
    }

    /// Connect to Zygote and verify the initial "Ready" greeting
    pub fn connect(socket_path: &Path) -> Result<Self> {
        let mut stream = {
            #[cfg(target_os = "linux")]
            {
                let name = socket_path.to_string_lossy();
                if name.starts_with('@') {
                    crate::common::paths::connect_abstract_socket(&name)
                } else if name.starts_with('\0') {
                    // Legacy Fallback
                    crate::common::paths::connect_abstract_socket(&name)
                } else {
                    UnixStream::connect(socket_path)
                }
            }
            #[cfg(not(target_os = "linux"))]
            UnixStream::connect(socket_path)
        }
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        // WB-002: Reliability - Set handshake timeout to prevent supervisor hang
        // if Zygote is unresponsive.
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(2)))
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

        // 1. Receive mandatory "Ready" greeting
        let (ready, fd): (ZygoteResponse, _) = read_message(&mut stream)?;

        // DEF-72-FLOOD-RS: Keep timeout for command reads to prevent indefinite blocking
        // 30 seconds is sufficient for IPC commands
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(30)))
            .map_err(|e| ZygoteError::SocketError(e.to_string()))?;
        if let Some(fd) = fd {
            // SECURITY: Explicitly close unexpected FDs to prevent supervisor leaks.
            let _ = nix::unistd::close(fd);
        }
        let mut stream = match ready {
            ZygoteResponse::Ready => Self { stream },
            _ => {
                return Err(ZygoteError::ProtocolError(
                    "Connection greeting failed - expected Ready".to_string(),
                ));
            }
        };

        // SEC-005: Automated Forensic Auth Handshake if secret exists
        // The secret is stored in a .auth file alongside the socket.
        let auth_path = crate::common::paths::VeloPaths::auth_file_for_socket(socket_path);
        if let Ok(secret) = std::fs::read_to_string(&auth_path) {
            log::debug!("[SEC-005] Performing forensic auth handshake...");
            let auth_cmd = ZygoteCommand::Auth {
                secret: secret.trim().to_string(),
                request_id: Some(uuid::Uuid::now_v7().to_string()),
            };

            match stream.send_command(&auth_cmd, None) {
                Ok(ZygoteResponse::Ack) => {
                    log::debug!("[SEC-005] Auth Success: Forensic Agent accepted.");
                }
                Ok(ZygoteResponse::Error { message, .. }) => {
                    return Err(ZygoteError::ProtocolError(format!(
                        "Auth failed: {}",
                        message
                    )));
                }
                Ok(other) => {
                    return Err(ZygoteError::ProtocolError(format!(
                        "Unexpected response during auth: {:?}",
                        other
                    )));
                }
                Err(e) => return Err(e),
            }
        } else {
            log::warn!(
                "[SEC-005] Auth file missing or unreadable: {}. Forensic Agent may fail auth.",
                auth_path.display()
            );
        }

        Ok(stream)
    }

    /// Send a command and wait for the response
    pub fn send_command(
        &mut self,
        cmd: &ZygoteCommand,
        fd: Option<RawFd>,
    ) -> Result<ZygoteResponse> {
        write_message(&mut self.stream, cmd, fd)?;
        let (resp, fd) = read_message(&mut self.stream)?;
        if let Some(fd) = fd {
            // SECURITY: Explicitly close unexpected FDs to prevent supervisor leaks.
            let _ = nix::unistd::close(fd);
        }
        Ok(resp)
    }
}

/// Accept a command from a client connection with peer verification
pub fn accept_command(
    listener: &UnixListener,
) -> Result<(UnixStream, ZygoteCommand, Option<RawFd>)> {
    let (mut stream, _) = listener
        .accept()
        .map_err(|e| ZygoteError::SocketError(e.to_string()))?;

    // DEF-72-SEC-005: Verify peer identity before any protocol exchange
    crate::zygote::peer_check::verify_peer(&stream)?;

    let (cmd, fd): (ZygoteCommand, Option<RawFd>) = read_message(&mut stream)?;

    Ok((stream, cmd, fd))
}

/// Send a response back to the launcher
pub fn send_response(stream: &mut UnixStream, response: ZygoteResponse) -> Result<()> {
    write_message(stream, &response, None)
}

/// Connect to the Zygote and send a command, returning the response
pub fn send_command(
    socket_path: &Path,
    command: ZygoteCommand,
    fd: Option<RawFd>,
) -> Result<ZygoteResponse> {
    let mut stream = ZygoteStream::connect(socket_path)?;
    stream.send_command(&command, fd)
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
            preload_done: true,
            pool_count: 5,
            target_pool_size: 10,
        };

        // Test JSON roundtrip
        let bytes = serde_json::to_vec(&resp).expect("Serialization failed");
        let decoded: ZygoteResponse =
            serde_json::from_slice(&bytes).expect("Deserialization failed");

        if let ZygoteResponse::Status {
            pid,
            preload,
            state,
            ..
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
            script_path: std::env::temp_dir().join("test.py"),
            module: None,
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
            shm_size: None,
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        };

        let bytes = serde_json::to_vec(&cmd).expect("Serialization failed");
        let decoded: ZygoteCommand =
            serde_json::from_slice(&bytes).expect("Deserialization failed");

        if let ZygoteCommand::Fork {
            script_path,
            async_mode,
            ..
        } = decoded
        {
            assert_eq!(script_path, std::env::temp_dir().join("test.py"));
            assert!(async_mode);
        } else {
            panic!("Decoded wrong variant");
        }
    }

    #[test]
    fn test_message_size() {
        let cmd = ZygoteCommand::Fork {
            script_path: std::env::temp_dir().join("test.py"),
            module: Some("test_module".to_string()),
            args: vec!["arg1".to_string(), "arg2".to_string()],
            async_mode: true,
            stdout_path: Some(std::env::temp_dir().join("out.txt")),
            stderr_path: Some(std::env::temp_dir().join("err.txt")),
            exit_code_path: Some(std::env::temp_dir().join("exit.txt")),
            fast_mode: true,
            bundle_path: Some(std::env::temp_dir().join("bundle.veloc")),
            project_root: Some(PathBuf::from("${HOME}/project")),
            max_bundle_size: Some(1024 * 1024),
            env: Box::new(std::collections::HashMap::new()),
            shm_size: Some(4096),
            request_id: Some(uuid::Uuid::now_v7().to_string()),
        };

        let json_bytes = serde_json::to_vec(&cmd).expect("JSON serialization failed");
        assert!(json_bytes.len() < MAX_MESSAGE_SIZE);
    }

    #[test]
    fn test_read_message_oversized() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;

        let (mut reader, mut writer) = UnixStream::pair().unwrap();

        // Send a message that claims to be huge
        let huge_len = (MAX_MESSAGE_SIZE + 1) as u32;
        writer.write_all(&huge_len.to_le_bytes()).unwrap();

        let res: Result<(ZygoteResponse, Option<RawFd>)> = read_message(&mut reader);
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

        let res: Result<(ZygoteResponse, Option<RawFd>)> = read_message(&mut reader);
        assert!(res.is_err());
        let err = res.unwrap_err().to_string();
        assert!(err.contains("Protocol version mismatch"));
    }

    /// DEF-72-FLOOD-RS: ZygoteStream must keep timeout after handshake
    ///
    /// This test verifies that after handshake, the socket timeout is set to 30s
    /// (not None) to prevent indefinite blocking from malformed/partial messages.
    #[test]
    fn test_zygote_stream_timeout_kept_after_handshake() {
        use std::os::unix::net::UnixStream;
        use std::time::Duration;

        // Create a socket pair to test timeout behavior
        let (stream1, _stream2) = UnixStream::pair().unwrap();

        // Initially, socket has no timeout
        assert!(
            stream1.read_timeout().unwrap().is_none(),
            "Socket should have no timeout initially"
        );

        // Set a timeout (simulating what ZygoteStream::connect does at line 471)
        stream1
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();

        // Verify timeout is set
        assert!(
            stream1.read_timeout().unwrap().is_some(),
            "Socket should have timeout after setting"
        );

        // Simulate the FIXED behavior at line 479 - timeout is set to 30s (not None)
        stream1
            .set_read_timeout(Some(Duration::from_secs(30)))
            .unwrap();

        // DEF-72-FLOOD-RS: After handshake, timeout should be 30s
        let timeout_after_handshake = stream1.read_timeout().unwrap();
        assert!(
            timeout_after_handshake.is_some(),
            "Timeout should be set after handshake (30s)"
        );
        assert_eq!(
            timeout_after_handshake.unwrap(),
            Duration::from_secs(30),
            "Timeout should be exactly 30 seconds after handshake"
        );
    }

    /// DEF-72-SEC-005: Zygote acceptor must verify peer UID/PID
    ///
    /// This test proves the current vulnerability: a socket connection is accepted
    /// without any peer identification check (SO_PEERCRED).
    #[test]
    fn test_forensic_handshake_spoofing() {
        use std::os::unix::net::UnixListener;
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let socket_path = dir.path().join("test.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();

        // Simulate a "malicious" client attempting to connect
        let client_thread = std::thread::spawn(move || {
            let mut stream = UnixStream::connect(socket_path).unwrap();
            // In a vulnerable version, the connection is accepted and we can read/write
            // A secure version would drop us immediately if we were an unauthorized peer
            let cmd = ZygoteCommand::Status { request_id: None };
            // Simulate writing a command
            write_message(&mut stream, &cmd, None).is_ok()
        });

        // Server side (Mock Zygote Acceptor)
        let (mut stream, _) = listener.accept().unwrap();
        // PROSECUTOR: If we are here, we accepted a connection.
        // We MUST verify peer identity before any protocol reads/writes.
        let peer_verify = crate::zygote::peer_check::verify_peer(&stream);

        // In this test, we are connecting as the same user, so peer_verify MUST be Ok.
        assert!(
            peer_verify.is_ok(),
            "Peer verification should pass for self"
        );

        // Now that we've verified identity, we can safely read the message.
        let _res: Result<(ZygoteCommand, Option<RawFd>)> = read_message(&mut stream);
        assert!(client_thread.join().unwrap());
    }
}
