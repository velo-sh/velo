use super::error::{Result, ZygoteError};
use nix::sys::socket::{getsockopt, sockopt};
use std::os::unix::net::UnixStream;

/// Verify that the peer connecting to the Zygote socket is authorized.
///
/// We use PeerCredentials to get the UID of the connecting process.
/// Only processes running as the same user (UID) are allowed to connect.
pub fn verify_peer(stream: &UnixStream) -> Result<()> {
    #[cfg(target_os = "linux")]
    let creds = getsockopt(stream, sockopt::PeerCredentials)
        .map_err(|e| ZygoteError::SocketError(format!("Failed to get peer credentials: {}", e)))?;

    #[cfg(target_os = "macos")]
    let creds = getsockopt(stream, sockopt::LocalPeerCred)
        .map_err(|e| ZygoteError::SocketError(format!("Failed to get peer credentials: {}", e)))?;

    let current_uid = unsafe { libc::getuid() };

    // Nix 0.27 Ucred has a .uid() method
    if creds.uid() != current_uid {
        return Err(ZygoteError::ProtocolError(format!(
            "Unauthorized peer: UID {} (expected {})",
            creds.uid(),
            current_uid
        )));
    }

    Ok(())
}
