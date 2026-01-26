//! Kubernetes Hardware Detection
//!
//! RFC-0011 K8s Review: Detect CPU quotas to avoid throttling.
//!
//! Kubernetes uses cgroups to limit CPU usage. Standard `available_parallelism()`
//! returns the node's CPU count, not the container's quota. This leads to
//! spawning too many workers and causing aggressive throttling.
//!
//! This module reads `/sys/fs/cgroup/cpu.max` (Cgroup v2) to determine
//! the actual available CPU quota.

use std::fs;
use std::path::Path;

/// Get the CPU limit from cgroup v2 quotas.
///
/// Returns `None` if:
/// - Not running on Linux
/// - Cgroup file not found
/// - Quota is "max" (unlimited)
/// - Error parsing file
///
/// RFC-0011 K8s Review: `cpu.max` format is `$MAX $PERIOD`
pub fn get_cgroup_cpu_limit() -> Option<u32> {
    if cfg!(target_os = "linux") {
        read_cgroup_cpu_max("/sys/fs/cgroup/cpu.max")
    } else {
        None
    }
}

/// Internal helper to read and parse cpu.max file.
/// Exposed for testing with mock files.
fn read_cgroup_cpu_max<P: AsRef<Path>>(path: P) -> Option<u32> {
    let content = fs::read_to_string(path).ok()?;
    let parts: Vec<&str> = content.split_whitespace().collect();

    if parts.len() < 2 {
        return None;
    }

    let quota_str = parts[0];
    let period_str = parts[1];

    // "max" means no limit
    if quota_str == "max" {
        return None;
    }

    let quota: u64 = quota_str.parse().ok()?;
    let period: u64 = period_str.parse().ok()?;

    if period == 0 {
        return None;
    }

    // Calculate ceil(quota / period) to handle fractional cores gracefully
    let limit = quota.div_ceil(period);

    // Ensure at least 1 core
    Some(limit.max(1) as u32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_parse_cgroup_cpu_max_exact() {
        let mut file = NamedTempFile::new().unwrap();
        write!(file, "200000 100000").unwrap();

        let limit = read_cgroup_cpu_max(file.path());
        assert_eq!(limit, Some(2));
    }

    #[test]
    fn test_parse_cgroup_cpu_max_fractional_round_up() {
        // 1.5 CPUs -> should round up to 2 workers to utilize potential burst
        let mut file = NamedTempFile::new().unwrap();
        write!(file, "150000 100000").unwrap();

        let limit = read_cgroup_cpu_max(file.path());
        assert_eq!(limit, Some(2));
    }

    #[test]
    fn test_parse_cgroup_cpu_max_small_fraction() {
        // 0.2 CPUs -> should be at least 1 worker
        let mut file = NamedTempFile::new().unwrap();
        write!(file, "20000 100000").unwrap();

        let limit = read_cgroup_cpu_max(file.path());
        assert_eq!(limit, Some(1));
    }

    #[test]
    fn test_parse_cgroup_cpu_max_unlimited() {
        let mut file = NamedTempFile::new().unwrap();
        write!(file, "max 100000").unwrap();

        let limit = read_cgroup_cpu_max(file.path());
        assert_eq!(limit, None);
    }

    #[test]
    fn test_parse_cgroup_invalid_format() {
        let mut file = NamedTempFile::new().unwrap();
        write!(file, "invalid").unwrap();

        let limit = read_cgroup_cpu_max(file.path());
        assert_eq!(limit, None);
    }
}
