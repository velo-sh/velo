//! Hardware detection for `velo info`.
//!
//! Detects system hardware information including CPU, memory, and architecture.

/// System hardware information.
#[derive(Debug, Clone)]
pub struct HardwareInfo {
    pub cpu: String,
    pub cores: u32,
    pub memory_gb: u32,
    pub arch: String,
}

impl HardwareInfo {
    /// Detect hardware information for the current system.
    #[cfg(target_os = "macos")]
    pub fn detect() -> Self {
        use std::process::Command;

        // Get CPU info
        let cpu = Command::new("sysctl")
            .args(["-n", "machdep.cpu.brand_string"])
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|| "Unknown".to_string());

        // Get core count
        let cores = Command::new("sysctl")
            .args(["-n", "hw.ncpu"])
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);

        // Get memory in bytes, convert to GB
        let memory_gb = Command::new("sysctl")
            .args(["-n", "hw.memsize"])
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| s.trim().parse::<u64>().ok())
            .map(|bytes| (bytes / (1024 * 1024 * 1024)) as u32)
            .unwrap_or(0);

        // Get architecture
        let arch = std::env::consts::ARCH.to_string();

        Self {
            cpu,
            cores,
            memory_gb,
            arch,
        }
    }

    /// Detect hardware information for Linux.
    #[cfg(target_os = "linux")]
    pub fn detect() -> Self {
        use std::fs;
        use std::process::Command;

        // Get CPU info from /proc/cpuinfo
        let cpu = fs::read_to_string("/proc/cpuinfo")
            .ok()
            .and_then(|content| {
                content
                    .lines()
                    .find(|l| l.starts_with("model name"))
                    .and_then(|l| l.split(':').nth(1))
                    .map(|s| s.trim().to_string())
            })
            .unwrap_or_else(|| "Unknown".to_string());

        // Get core count
        let cores = Command::new("nproc")
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);

        // Get memory from /proc/meminfo
        let memory_gb = fs::read_to_string("/proc/meminfo")
            .ok()
            .and_then(|content| {
                content
                    .lines()
                    .find(|l| l.starts_with("MemTotal"))
                    .and_then(|l| {
                        l.split_whitespace()
                            .nth(1)
                            .and_then(|s| s.parse::<u64>().ok())
                    })
            })
            .map(|kb| (kb / (1024 * 1024)) as u32)
            .unwrap_or(0);

        let arch = std::env::consts::ARCH.to_string();

        Self {
            cpu,
            cores,
            memory_gb,
            arch,
        }
    }

    /// Fallback for other platforms.
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    pub fn detect() -> Self {
        Self {
            cpu: "Unknown".to_string(),
            cores: 0,
            memory_gb: 0,
            arch: std::env::consts::ARCH.to_string(),
        }
    }

    /// Format hardware info for display.
    pub fn format(&self) -> String {
        format!(
            "▸ Hardware\n\
             ├─ CPU:     {}\n\
             ├─ Cores:   {}\n\
             ├─ Memory:  {} GB\n\
             └─ Arch:    {}",
            self.cpu, self.cores, self.memory_gb, self.arch
        )
    }
}

// ============================================================================
// TESTS
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hardware_detection() {
        let info = HardwareInfo::detect();

        // Should get some CPU info
        assert!(!info.cpu.is_empty());

        // Should get at least 1 core
        assert!(info.cores >= 1);

        // Should get some memory (at least 1 GB)
        assert!(info.memory_gb >= 1);

        // Arch should be known
        assert!(!info.arch.is_empty());
    }

    #[test]
    fn test_hardware_format() {
        let info = HardwareInfo {
            cpu: "Test CPU".to_string(),
            cores: 8,
            memory_gb: 16,
            arch: "x86_64".to_string(),
        };

        let formatted = info.format();

        assert!(formatted.contains("Hardware"));
        assert!(formatted.contains("Test CPU"));
        assert!(formatted.contains("8"));
        assert!(formatted.contains("16 GB"));
        assert!(formatted.contains("x86_64"));
    }
}
