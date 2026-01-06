//! Socket Hygiene - Utilities for safe socket file management
//!
//! RFC-0011 B.2.4: Clean stale sockets before binding.
//!
//! ## Safety
//!
//! - Checks file type before deletion (S_IFSOCK)
//! - Async-safe using tokio::fs
//! - Logs operations for debugging

use std::path::{Path, PathBuf};
use std::process::Command;
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

/// RFC-0011 D.1: Generate Abstract Namespace Socket name (Linux only).
///
/// Abstract Namespace Sockets have advantages over filesystem sockets:
/// - No stale socket files after crash (kernel manages lifecycle)
/// - No need for `unlink()` before binding
/// - No filesystem permissions to manage
///
/// Returns `Some(name)` on Linux, `None` on other platforms.
///
/// # Format
/// `\0velo-worker-{worker_id}` (leading null byte marks abstract namespace)
#[cfg(target_os = "linux")]
pub fn generate_abstract_socket_name(worker_id: u64) -> String {
    format!("\0velo-worker-{}", worker_id)
}

/// On non-Linux, abstract namespace sockets are not supported.
/// Returns None - caller should fall back to filesystem sockets.
#[cfg(not(target_os = "linux"))]
pub fn generate_abstract_socket_name(_worker_id: u64) -> Option<String> {
    None
}

/// Check if the platform supports abstract namespace sockets.
#[inline]
pub fn supports_abstract_sockets() -> bool {
    cfg!(target_os = "linux")
}

// =========================================================================
// RFC-0012: Environment Shield (Surgical Sanitization)
// =========================================================================

/// Result type for security operations
pub type SecurityResult<T> = std::result::Result<T, String>;

/// RFC-0012: Environment Shield (Surgical Sanitization)
///
/// Prevents "Environment Starvation" while blocking "Dangerous Toxins".
pub struct EnvironmentShield {
    trusted_prefixes: Vec<PathBuf>,
}

impl Default for EnvironmentShield {
    fn default() -> Self {
        Self::new()
    }
}

impl EnvironmentShield {
    pub fn new() -> Self {
        let mut trusted = Vec::new();

        // 1. Project Root (Highest priority)
        if let Ok(cwd) = std::env::current_dir() {
            trusted.push(cwd);
        }

        // 2. Velo Executable Directory (Essential for child spawns)
        if let Ok(exe) = std::env::current_exe()
            && let Some(parent) = exe.parent()
        {
            trusted.push(parent.to_path_buf());
        }

        // 3. Standard System Prefixes (RFC §3.5)
        for p in &[
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/opt/homebrew",
            "/opt/local",
        ] {
            trusted.push(PathBuf::from(p));
        }

        // 4. User Home Directory (RFC §3.5: User-trusted space)
        if let Ok(home) = std::env::var("HOME") {
            trusted.push(PathBuf::from(home));
        }

        // 5. Active VirtualEnv
        if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
            trusted.push(PathBuf::from(venv));
        }
        if let Ok(conda) = std::env::var("CONDA_PREFIX") {
            trusted.push(PathBuf::from(conda));
        }

        Self {
            trusted_prefixes: trusted
                .into_iter()
                .filter_map(|p| p.canonicalize().ok())
                .collect(),
        }
    }

    /// Apply surgical whitelist and provenance guard to a Command
    pub fn apply(&self, cmd: &mut Command) -> SecurityResult<()> {
        cmd.env_clear();

        // RFC §3.1: Mandatory Whitelist
        const WHITELIST: &[&str] = &[
            "PATH",
            "HOME",
            "USER",
            "TMPDIR",
            "XDG_RUNTIME_DIR",
            "SHELL",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TZ",
            // macOS Essentials
            "__CF_USER_TEXT_ENCODING",
            "MallocNanoZone",
            "XPC_FLAGS",
            "XPC_SERVICE_NAME",
            "TERM_PROGRAM",
            "TERM",
        ];

        for var in WHITELIST {
            if let Ok(val) = std::env::var(var) {
                // Special handling for PATH (Provenance Guard §3.5)
                if *var == "PATH" {
                    let cleaned = self.validate_path_variable(&val)?;
                    cmd.env(var, cleaned);
                } else {
                    cmd.env(var, val);
                }
            }
        }

        // RFC §4.0: PYTHONPATH is blacklisted by default unless surgically verified
        if let Ok(val) = std::env::var("PYTHONPATH")
            && let Ok(cleaned) = self.validate_path_variable(&val)
            && !cleaned.is_empty()
        {
            cmd.env("PYTHONPATH", cleaned);
        }

        // 2. High-Performance Isolation (RFC-0011 HPC-001)
        cmd.env("OMP_NUM_THREADS", "1");
        cmd.env("MKL_NUM_THREADS", "1");
        cmd.env("OPENBLAS_NUM_THREADS", "1");
        cmd.env("VECLIB_MAXIMUM_THREADS", "1");
        cmd.env("NUMEXPR_NUM_THREADS", "1");

        // 3. Python Specific Isolation
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");
        cmd.env("PYTHONUNBUFFERED", "1");
        cmd.env("PYTHONIOENCODING", "utf-8");
        cmd.env("PYTHONUTF8", "1");

        Ok(())
    }

    /// RFC §3.5: Environment Provenance Guard
    /// Validates that every entry in a path-like variable points to a trusted location.
    pub fn validate_path_variable(&self, value: &str) -> SecurityResult<String> {
        let mut valid_entries = Vec::new();
        let sep = if cfg!(windows) { ';' } else { ':' };

        for entry in value.split(sep) {
            if entry.is_empty() {
                continue;
            }

            let path = PathBuf::from(entry);

            // Fail-Fast: Canonicalization must succeed for trust verification
            // If it fails, it's likely a non-existent directory which is harmless to skip
            let canonical = match path.canonicalize() {
                Ok(p) => p,
                Err(_) => {
                    eprintln!("⚠️ Warning: Skipping invalid path entry: {:?}", entry);
                    continue;
                }
            };

            // Check if entry is within trusted prefixes
            if self.is_trusted(&canonical) {
                valid_entries.push(entry.to_string());
            } else {
                eprintln!("🚨 Security: Scrubbing untrusted path entry: {:?}", entry);
            }
        }

        Ok(valid_entries.join(&sep.to_string()))
    }

    fn is_trusted(&self, path: &Path) -> bool {
        self.trusted_prefixes
            .iter()
            .any(|prefix| path.starts_with(prefix))
    }
}

/// RFC-0012 §3.6: Apply standard FD and Signal hygiene to a Command.
///
/// Ensures:
/// 1. Signal mask is reset (no inherited blocked signals)
/// 2. SIGINT/SIGTERM are reset to default
/// 3. All FDs > 2 are closed (prevents leaks)
#[cfg(unix)]
pub fn apply_standard_hygiene(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    unsafe {
        cmd.pre_exec(|| {
            // 1. Reset Signal Mask (SEC-FS-002)
            let mut mask: libc::sigset_t = std::mem::zeroed();
            libc::sigemptyset(&mut mask);
            libc::pthread_sigmask(libc::SIG_SETMASK, &mask, std::ptr::null_mut());

            // 2. Reset SIGINT/SIGTERM to default (MAC-P0-002)
            libc::signal(libc::SIGINT, libc::SIG_DFL);
            libc::signal(libc::SIGTERM, libc::SIG_DFL);

            // 3. FD Purge (SEC-FS-002)
            let mut rl = libc::rlimit {
                rlim_cur: 0,
                rlim_max: 0,
            };
            libc::getrlimit(libc::RLIMIT_NOFILE, &mut rl);
            let max_fd = if rl.rlim_cur > 0 {
                rl.rlim_cur as i32
            } else {
                1024
            };

            for fd in 3..max_fd {
                libc::close(fd);
            }

            Ok(())
        });
    }
}

/// No-op on non-Unix platforms
#[cfg(not(unix))]
pub fn apply_standard_hygiene(_cmd: &mut Command) {}

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

    // =========================================================================
    // RFC-0011 D.1: Abstract Namespace Socket Tests
    // =========================================================================

    #[test]
    fn test_supports_abstract_sockets() {
        // On macOS: should return false
        // On Linux: should return true
        let supported = supports_abstract_sockets();

        #[cfg(target_os = "linux")]
        assert!(supported, "Linux should support abstract sockets");

        #[cfg(not(target_os = "linux"))]
        assert!(!supported, "Non-Linux should not support abstract sockets");
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn test_generate_abstract_socket_name_linux() {
        let name = generate_abstract_socket_name(42);
        assert!(name.starts_with('\0'), "Should start with null byte");
        assert!(name.contains("velo-worker-42"));
    }

    #[test]
    #[cfg(not(target_os = "linux"))]
    fn test_generate_abstract_socket_name_non_linux() {
        let result = generate_abstract_socket_name(42);
        assert!(result.is_none(), "Non-Linux should return None");
    }
}
