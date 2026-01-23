//! Process memory usage tracking for Velo diagnostics.
//!
//! Provides a cross-platform way to get the Resident Set Size (RSS)
//! of the current process using the `ps` command.

use std::process::Command;

/// Get the current process RSS in bytes.
pub fn get_process_rss_bytes() -> Option<u64> {
    let pid = std::process::id();

    // ps -o rss= -p <pid> returns RSS in KB
    let output = Command::new("ps")
        .args(["-o", "rss=", "-p", &pid.to_string()])
        .output()
        .ok()?;

    if output.status.success() {
        let s = String::from_utf8_lossy(&output.stdout);
        s.trim().parse::<u64>().ok().map(|kb| kb * 1024)
    } else {
        None
    }
}
