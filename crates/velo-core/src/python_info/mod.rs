//! Python ABI detection for cache compatibility.
//!
//! Detects Python version, ABI tag, and platform tag to ensure
//! cached sys.path is compatible with current Python interpreter.

use anyhow::{Context, Result};
use rkyv::{Archive, Deserialize, Serialize};
use std::fmt;
use std::path::Path;
use std::process::Command;

/// Python version (major.minor.patch).
#[derive(Archive, Deserialize, Serialize, Debug, Clone, PartialEq, Default)]
#[rkyv(compare(PartialEq), derive(Debug))]
pub struct PythonVersion {
    pub major: u8,
    pub minor: u8,
    pub patch: u8,
}

impl PythonVersion {
    /// Parse version string like "3.11.5" into PythonVersion.
    pub fn parse(version_str: &str) -> Result<Self> {
        let parts: Vec<&str> = version_str.trim().split('.').collect();
        if parts.len() < 2 {
            anyhow::bail!("Invalid version string: {}", version_str);
        }

        let major = parts[0]
            .parse()
            .with_context(|| format!("Invalid major version: {}", parts[0]))?;
        let minor = parts[1]
            .parse()
            .with_context(|| format!("Invalid minor version: {}", parts[1]))?;
        let patch = if parts.len() > 2 {
            parts[2].parse().unwrap_or(0)
        } else {
            0
        };

        Ok(Self {
            major,
            minor,
            patch,
        })
    }
}

impl fmt::Display for PythonVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}.{}", self.major, self.minor, self.patch)
    }
}

/// Complete Python interpreter information for ABI compatibility.
#[derive(Debug, Clone)]
pub struct PythonInfo {
    pub version: PythonVersion,
    /// ABI tag like "cpython-311-darwin" or "cp311"
    pub abi_tag: String,
    /// Platform tag like "macosx_14_0_arm64" or "linux_x86_64"
    pub platform_tag: String,
}

impl PythonInfo {
    /// Detect Python information by running the interpreter.
    pub fn detect(python_path: &Path) -> Result<Self> {
        let script = r#"
import sys, sysconfig
v = sys.version_info
print(f"{v.major}.{v.minor}.{v.micro}")
print(sysconfig.get_config_var('SOABI') or 'unknown')
print(sysconfig.get_platform().replace('-', '_').replace('.', '_'))
"#;

        let output = Command::new(python_path)
            .args(["-c", script])
            .output()
            .with_context(|| format!("Failed to run Python at {:?}", python_path))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("Python failed: {}", stderr);
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let lines: Vec<&str> = stdout.lines().collect();

        if lines.len() < 3 {
            anyhow::bail!("Unexpected Python output: {}", stdout);
        }

        let version = PythonVersion::parse(lines[0])?;
        let abi_tag = lines[1].to_string();
        let platform_tag = lines[2].to_string();

        Ok(Self {
            version,
            abi_tag,
            platform_tag,
        })
    }

    /// Check if this Python is ABI-compatible with a cached version.
    /// ABI tag must match exactly for C-extension compatibility.
    #[allow(dead_code)]
    pub fn is_abi_compatible(&self, cached: &PythonInfo) -> bool {
        self.abi_tag == cached.abi_tag
    }

    /// Check if Python version matches (ignoring patch level).
    #[allow(dead_code)]
    pub fn is_version_compatible(&self, cached: &PythonInfo) -> bool {
        self.version.major == cached.version.major && self.version.minor == cached.version.minor
    }

    /// Format for display in warnings.
    #[allow(dead_code)]
    pub fn display(&self) -> String {
        format!(
            "Python {} ({}-{})",
            self.version, self.abi_tag, self.platform_tag
        )
    }
}

// ============================================================================
// TESTS (TDD - written first)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -------------------------------------------------------------------------
    // PythonVersion Tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_python_version_parse_full() {
        let version = PythonVersion::parse("3.11.5").unwrap();
        assert_eq!(version.major, 3);
        assert_eq!(version.minor, 11);
        assert_eq!(version.patch, 5);
    }

    #[test]
    fn test_python_version_parse_major_minor_only() {
        let version = PythonVersion::parse("3.12").unwrap();
        assert_eq!(version.major, 3);
        assert_eq!(version.minor, 12);
        assert_eq!(version.patch, 0);
    }

    #[test]
    fn test_python_version_parse_with_whitespace() {
        let version = PythonVersion::parse("  3.11.5\n").unwrap();
        assert_eq!(version.major, 3);
        assert_eq!(version.minor, 11);
        assert_eq!(version.patch, 5);
    }

    #[test]
    fn test_python_version_parse_invalid() {
        assert!(PythonVersion::parse("invalid").is_err());
        assert!(PythonVersion::parse("3").is_err());
        assert!(PythonVersion::parse("").is_err());
    }

    #[test]
    fn test_python_version_to_string() {
        let version = PythonVersion {
            major: 3,
            minor: 11,
            patch: 5,
        };
        assert_eq!(version.to_string(), "3.11.5");
    }

    // -------------------------------------------------------------------------
    // PythonInfo Tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_abi_compatibility_same() {
        let info1 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 5,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        let info2 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 7,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        assert!(info1.is_abi_compatible(&info2));
    }

    #[test]
    fn test_abi_compatibility_different() {
        let info1 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 0,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        let info2 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 12,
                patch: 0,
            },
            abi_tag: "cpython-312-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        assert!(!info1.is_abi_compatible(&info2));
    }

    #[test]
    fn test_version_compatibility() {
        let info1 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 5,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        let info2 = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 9,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        // Patch version difference should still be compatible
        assert!(info1.is_version_compatible(&info2));
    }

    #[test]
    fn test_display_format() {
        let info = PythonInfo {
            version: PythonVersion {
                major: 3,
                minor: 11,
                patch: 5,
            },
            abi_tag: "cpython-311-darwin".to_string(),
            platform_tag: "macosx_14_0_arm64".to_string(),
        };
        assert_eq!(
            info.display(),
            "Python 3.11.5 (cpython-311-darwin-macosx_14_0_arm64)"
        );
    }

    // -------------------------------------------------------------------------
    // Integration Test - Detect from actual Python
    // -------------------------------------------------------------------------

    #[test]
    fn test_detect_from_system_python() {
        // This test requires python3 to be installed
        use std::process::Command;

        let which_output = Command::new("which").arg("python3").output();
        if which_output.is_err() {
            eprintln!("Skipping test_detect_from_system_python: python3 not found");
            return;
        }

        let python_path_output = std::process::Command::new("which").arg("python3").output();

        if python_path_output.is_err() {
            eprintln!("Skipping test: python3 not found");
            return;
        }

        // RFC-0038: Skip in CI/Docker hardening where system python is sabotaged
        if std::env::var("CI").is_ok() || std::env::var("GITHUB_ACTIONS").is_ok() {
            eprintln!("Skipping test in CI environment (Sovereignty-First Hardening active)");
            return;
        }

        let output = python_path_output.unwrap();

        let python_path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let python = Path::new(&python_path);

        let info = PythonInfo::detect(python);
        assert!(info.is_ok(), "Failed to detect Python info: {:?}", info);

        let info = info.unwrap();
        assert!(info.version.major >= 3, "Expected Python 3+");
        assert!(!info.abi_tag.is_empty(), "ABI tag should not be empty");
        assert!(
            !info.platform_tag.is_empty(),
            "Platform tag should not be empty"
        );
    }
}
