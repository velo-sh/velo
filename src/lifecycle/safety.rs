//! Socket Hygiene - Utilities for safe socket file management
//!
//! RFC-0011 B.2.4: Clean stale sockets before binding.
//!
//! ## Safety
//!
//! - Checks file type before deletion (S_IFSOCK)
//! - Async-safe using tokio::fs
//! - Logs operations for debugging

use std::path::Path;
use tokio::fs;

/// Clean up a stale socket file if it exists.
///
/// RFC-0011 B.2.4: Socket Hygiene
/// - Checks if path exists and is a socket
/// - Only removes if it's actually a socket file
/// - Logs operations for debugging
///
/// # Safety
///
/// This is safe because:
/// - We verify the file is a socket before removal
/// - We use atomic operations
/// - Errors are logged but don't cause panic
pub async fn unlink_socket_if_exists(path: &Path) -> std::io::Result<()> {
    if !path.exists() {
        return Ok(());
    }

    let metadata = fs::metadata(path).await?;

    // Check if it's a socket (S_IFSOCK = 0o140000)
    #[cfg(unix)]
    {
        use std::os::unix::fs::FileTypeExt;

        if metadata.file_type().is_socket() {
            fs::remove_file(path).await?;
            eprintln!("🧹 Cleaned up stale socket: {:?}", path);
        } else {
            eprintln!(
                "⚠️ Warning: {:?} exists but is not a socket (type: {:?})",
                path,
                metadata.file_type()
            );
        }
    }

    #[cfg(not(unix))]
    {
        // On non-Unix platforms, just try to remove if it's a file
        if metadata.is_file() {
            fs::remove_file(path).await?;
        }
    }

    Ok(())
}

/// Synchronous version for use in non-async contexts.
pub fn unlink_socket_if_exists_sync(path: &Path) -> std::io::Result<()> {
    if !path.exists() {
        return Ok(());
    }

    let metadata = std::fs::metadata(path)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::FileTypeExt;

        if metadata.file_type().is_socket() {
            std::fs::remove_file(path)?;
            eprintln!("🧹 Cleaned up stale socket: {:?}", path);
        } else {
            eprintln!("⚠️ Warning: {:?} exists but is not a socket!", path);
        }
    }

    #[cfg(not(unix))]
    {
        if metadata.is_file() {
            std::fs::remove_file(path)?;
        }
    }

    Ok(())
}

/// Ensure parent directory exists with proper permissions.
///
/// Creates the directory with 0700 permissions for security.
pub async fn ensure_socket_directory(path: &Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent()
        && !parent.exists()
    {
        fs::create_dir_all(parent).await?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let perms = std::fs::Permissions::from_mode(0o700);
            fs::set_permissions(parent, perms).await?;
        }
    }
    Ok(())
}

/// Set FD_CLOEXEC flag on a file descriptor.
///
/// RFC-0011 C.1: Prevents file descriptor leaks when forking workers.
/// FDs with CLOEXEC are automatically closed in child processes after exec().
///
/// # Safety
///
/// Uses libc::fcntl which is safe for valid file descriptors.
#[cfg(unix)]
pub fn set_cloexec(fd: std::os::unix::io::RawFd) -> std::io::Result<()> {
    // Get existing flags
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags < 0 {
        return Err(std::io::Error::last_os_error());
    }

    // Set FD_CLOEXEC
    let result = unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) };
    if result < 0 {
        return Err(std::io::Error::last_os_error());
    }

    Ok(())
}

/// Set FD_CLOEXEC on all open file descriptors (except stdin/stdout/stderr).
///
/// RFC-0011 C.1: Call this before fork() to prevent FD leaks.
#[cfg(unix)]
pub fn set_cloexec_on_all_fds() -> std::io::Result<usize> {
    use std::fs;

    let mut count = 0;

    // Read /proc/self/fd to get all open FDs
    if let Ok(entries) = fs::read_dir("/proc/self/fd") {
        for entry in entries.flatten() {
            if let Ok(name) = entry.file_name().into_string()
                && let Ok(fd) = name.parse::<i32>()
                && fd > 2
                && set_cloexec(fd).is_ok()
            {
                count += 1;
            }
        }
    }

    Ok(count)
}

/// Generate a unique socket path for a worker.
///
/// Format: `/tmp/velo-{uid}/worker-{id}.sock`
pub fn generate_worker_socket_path(worker_id: u64) -> std::path::PathBuf {
    #[cfg(unix)]
    let socket_dir = {
        let uid = unsafe { libc::getuid() };
        std::path::PathBuf::from(format!("/tmp/velo-{}", uid))
    };

    #[cfg(not(unix))]
    let socket_dir = std::env::temp_dir().join("velo");

    socket_dir.join(format!("worker-{}.sock", worker_id))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixListener;
    use tempfile::TempDir;

    #[test]
    fn test_generate_worker_socket_path() {
        let path1 = generate_worker_socket_path(1);
        let path2 = generate_worker_socket_path(2);

        assert!(path1.to_string_lossy().contains("worker-1.sock"));
        assert!(path2.to_string_lossy().contains("worker-2.sock"));
        assert_ne!(path1, path2);
    }

    #[test]
    fn test_unlink_socket_if_exists_sync_not_exists() {
        let path = std::path::Path::new("/tmp/nonexistent-socket-12345.sock");
        let result = unlink_socket_if_exists_sync(path);
        assert!(result.is_ok());
    }

    #[test]
    fn test_unlink_socket_if_exists_sync_is_socket() {
        let temp_dir = TempDir::new().unwrap();
        let socket_path = temp_dir.path().join("test.sock");

        // Create a real socket
        let _listener = UnixListener::bind(&socket_path).unwrap();
        assert!(socket_path.exists());

        // Drop the listener so we can delete
        drop(_listener);

        // Now clean up
        let result = unlink_socket_if_exists_sync(&socket_path);
        assert!(result.is_ok());
        assert!(!socket_path.exists());
    }

    #[test]
    fn test_unlink_socket_if_exists_sync_not_socket() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("regular-file.txt");

        // Create a regular file
        std::fs::write(&file_path, "test content").unwrap();
        assert!(file_path.exists());

        // Should not delete regular file
        let result = unlink_socket_if_exists_sync(&file_path);
        assert!(result.is_ok());
        assert!(file_path.exists()); // File should still exist
    }

    // =========================================================================
    // TDD Cycle 4.1: FD_CLOEXEC
    // =========================================================================

    /// 🔴 RED: Test that FD_CLOEXEC is set on file descriptors
    #[test]
    fn test_set_cloexec_on_fd() {
        use std::fs::File;
        use std::os::unix::io::AsRawFd;

        // Create a temp file to get an FD
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test-fd.txt");
        let file = File::create(&file_path).unwrap();
        let fd = file.as_raw_fd();

        // Set FD_CLOEXEC
        let result = set_cloexec(fd);
        assert!(result.is_ok());

        // Verify FD_CLOEXEC is set
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        assert!(flags >= 0, "fcntl failed");
        assert!(flags & libc::FD_CLOEXEC != 0, "FD_CLOEXEC should be set");
    }
}
