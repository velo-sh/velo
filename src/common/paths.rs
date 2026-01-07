//! Centralized path logic for Velo (RFC-0012)
//!
//! Provides canonical resolution for:
//! - Socket directory (XDG_RUNTIME_DIR -> TMPDIR)
//! - Socket file path
//! - Permission enforcement (0700)

use std::path::{Path, PathBuf};

/// Maximum length for a unix socket path (legacy limit is 108, we use 104 for safety)
pub const SOCKET_PATH_LIMIT: usize = 104;

/// Protocol version for socket versioning
pub const PROTOCOL_VERSION: u8 = 1;

/// Get the canonical socket directory.
///
/// Priority:
/// 1. `XDG_RUNTIME_DIR/velo` (Linux standard)
/// 2. `TMPDIR/velo-{uid}` (Fallback)
/// 3. `/tmp/velo-{uid}` (Last resort)
///
/// Note: We intentionally avoid project hashing in the directory name for simplicity
/// and predictability in test environments (RFC-0012), unless strictly required for multi-tenant isolation.
/// Current decision: Use `velo-{uid}` to avoid path length issues.
pub fn get_socket_dir() -> PathBuf {
    let uid = unsafe { libc::getuid() };

    // 1. Try XDG_RUNTIME_DIR
    if let Ok(xdg) = std::env::var("XDG_RUNTIME_DIR") {
        let dir = PathBuf::from(xdg).join("velo");
        return dir;
    }

    // 2. Try TMPDIR provided by OS
    let dir_name = format!("velo-{}", uid);
    let tmp = std::env::temp_dir();
    let user_dir = tmp.join(&dir_name);

    // Check path length safety
    let test_socket = user_dir.join(format!("z-v{}.s", PROTOCOL_VERSION));
    if test_socket.to_string_lossy().len() <= SOCKET_PATH_LIMIT {
        return user_dir;
    }

    // 3. Fallback to /tmp if TMPDIR is too long (common on macOS)
    PathBuf::from("/tmp").join(dir_name)
}

/// Get the full socket path.
///
/// Respects `VELO_ZYGOTE_SOCKET` override.
pub fn get_socket_path() -> PathBuf {
    if let Some(path) = std::env::var("VELO_ZYGOTE_SOCKET")
        .ok()
        .filter(|p| !p.is_empty())
    {
        return PathBuf::from(path);
    }

    let dir = get_socket_dir();

    // Auto-create directory with strict permissions (RFC-0012)
    ensure_socket_dir(&dir);

    dir.join(format!("velo-zygote-v{:02x}.sock", PROTOCOL_VERSION))
}

/// Ensure directory exists with 0700 permissions.
pub fn ensure_socket_dir(dir: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;

    if !dir.exists() {
        let old_mask = unsafe { libc::umask(0o077) };
        let res = std::fs::create_dir_all(dir);
        unsafe { libc::umask(old_mask) };
        if res.is_err() {
            return false;
        }
    }

    // Force 0700
    if let Ok(metadata) = dir.metadata() {
        let mut perms = metadata.permissions();
        perms.set_mode(0o700);
        if std::fs::set_permissions(dir, perms).is_err() {
            return false;
        }
    }

    // Verify
    if let Ok(metadata) = dir.metadata() {
        let mode = metadata.permissions().mode() & 0o777;
        if mode != 0o700 {
            eprintln!(
                "⚠️ SECURITY: Socket dir has insecure permissions: {:o}",
                mode
            );
            // We warn but don't fail, mirroring current leniency logic (RFC-0012 allows strictness later)
        }
    }

    true
}
