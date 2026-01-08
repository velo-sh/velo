//! Velo configuration logic (RFC-0012)
//!
//! Parses [tool.velo] section from pyproject.toml and applies environment overrides.

use crate::common::paths::VeloPaths;
use std::path::Path;

/// Embedded SSOT for runtime defaults
const CONSTANTS_TOML: &str = include_str!("../config/constants.toml");

/// Velo configuration
#[derive(Debug, Clone)]
pub struct VeloConfig {
    /// Modules to preload in Zygote
    pub preload: Vec<String>,
    /// Maximum bundle size in Bytes
    pub max_bundle_size: usize,
    /// Zygote socket startup timeout in seconds
    pub zygote_socket_timeout: u64,
    /// Threshold in ms for "slow" imports
    pub slow_threshold_ms: u64,
    /// Trusted path prefixes for environment scrubbing
    pub security_trusted_prefixes: Vec<String>,
    /// Whitelisted environment variables
    pub security_env_whitelist: Vec<String>,
    /// Max threads for HPC libraries (OpenMP, MKL, etc)
    pub security_hpc_threads: usize,
}

impl Default for VeloConfig {
    fn default() -> Self {
        // VELO_ENV determines the security profile: dev (default), ci, prod
        let env_mode = std::env::var("VELO_ENV").unwrap_or_else(|_| "dev".to_string());

        // Detect OS at runtime
        let os_name = match std::env::consts::OS {
            "macos" => "macos",
            "linux" => "linux",
            _ => "linux", // Fallback to linux for other Unix
        };

        // Level 0: Global Base
        let base_prefixes =
            extract_default_str("security_base_trusted_prefixes").unwrap_or_default();
        let base_envs = extract_default_str("security_base_env_whitelist").unwrap_or_default();

        // Level 1: OS Base (merge with global base via ${BASE})
        let os_base_prefix_key = format!("security_{}_base_trusted_prefixes", os_name);
        let os_base_env_key = format!("security_{}_base_env_whitelist", os_name);

        let os_base_prefixes = extract_default_str(&os_base_prefix_key)
            .unwrap_or_default()
            .replace("${BASE}", &base_prefixes);
        let os_base_envs = extract_default_str(&os_base_env_key)
            .unwrap_or_default()
            .replace("${BASE}", &base_envs);

        // Level 2: OS + Environment (merge with OS base via ${OS_BASE})
        let final_prefix_key = format!("security_{}_{}_trusted_prefixes", os_name, env_mode);
        let final_env_key = format!("security_{}_{}_env_whitelist", os_name, env_mode);

        // Fallback to dev if profile not found
        let fallback_prefix_key = format!("security_{}_dev_trusted_prefixes", os_name);
        let fallback_env_key = format!("security_{}_dev_env_whitelist", os_name);

        let raw_prefixes = extract_default_str(&final_prefix_key)
            .or_else(|| extract_default_str(&fallback_prefix_key))
            .unwrap_or_default()
            .replace("${OS_BASE}", &os_base_prefixes);

        let raw_envs = extract_default_str(&final_env_key)
            .or_else(|| extract_default_str(&fallback_env_key))
            .unwrap_or_default()
            .replace("${OS_BASE}", &os_base_envs);

        Self {
            preload: Vec::new(),
            max_bundle_size: 1024 * 1024 * 1024, // 1GB default
            zygote_socket_timeout: extract_default_u64("socket_startup_timeout", 5),
            slow_threshold_ms: extract_default_u64("default_slow_threshold_ms", 100),
            security_trusted_prefixes: Self::parse_string_array(&raw_prefixes),
            security_env_whitelist: Self::parse_string_array(&raw_envs),
            security_hpc_threads: extract_default_u64("security_hpc_threads", 1) as usize,
        }
    }
}

/// Extract a string default from the embedded TOML
fn extract_default_str(key: &str) -> Option<String> {
    for line in CONSTANTS_TOML.lines() {
        let line = line.trim();
        if line.starts_with(key)
            && let Some((_, val)) = line.split_once('=')
        {
            return Some(val.trim().trim_matches('"').to_string());
        }
    }
    None
}

/// Public interface to extract path configuration (RFC-0012 Phase 6.5)
pub fn extract_path_config(key: &str) -> Option<String> {
    extract_default_str(key)
}

/// Extract a u64 default from the embedded TOML
fn extract_default_u64(key: &str, default: u64) -> u64 {
    for line in CONSTANTS_TOML.lines() {
        let line = line.trim();
        if line.starts_with(key) {
            let val = line
                .split_once('=')
                .and_then(|(_, v)| v.trim().parse().ok());
            if let Some(v) = val {
                return v;
            }
        }
    }
    default
}

impl VeloConfig {
    /// Read from pyproject.toml in current directory and apply overrides.
    pub fn from_pyproject_toml() -> Self {
        let path = VeloPaths::pyproject(Path::new("."));
        Self::load_with_overrides(&path)
    }

    /// Load default config and apply environment overrides.
    /// Useful when no pyproject.toml is present.
    pub fn from_env_only() -> Self {
        let mut config = Self::default();
        config.apply_env_overrides();
        config
    }

    /// Apply overrides from environment variables
    pub fn apply_env_overrides(&mut self) {
        if let Ok(val) = std::env::var("VELO_PRELOAD") {
            self.preload = Self::parse_string_array(&val);
        }
        if let Some(mb) = std::env::var("VELO_MAX_BUNDLE_SIZE")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
        {
            self.max_bundle_size = mb * 1024 * 1024;
        }
        if let Some(secs) = std::env::var("VELO_ZYGOTE_SOCKET_TIMEOUT")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
        {
            self.zygote_socket_timeout = secs;
        }
        if let Some(ms) = std::env::var("VELO_SLOW_THRESHOLD_MS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
        {
            self.slow_threshold_ms = ms;
        }
        if let Ok(val) = std::env::var("VELO_SECURITY_TRUSTED_PREFIXES") {
            self.security_trusted_prefixes = Self::parse_string_array(&val);
        }
        if let Ok(val) = std::env::var("VELO_SECURITY_ENV_WHITELIST") {
            self.security_env_whitelist = Self::parse_string_array(&val);
        }
        if let Some(n) = std::env::var("VELO_SECURITY_HPC_THREADS")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
        {
            self.security_hpc_threads = n;
        }
    }

    /// Read from specific path and apply environment overrides
    pub fn load_with_overrides(path: &Path) -> Self {
        let mut config = Self::from_path(path).unwrap_or_default();
        config.apply_env_overrides();
        config
    }

    /// Read from specific path
    pub fn from_path(path: &Path) -> Option<Self> {
        let content = std::fs::read_to_string(path).ok()?;
        Self::parse_toml(&content)
    }

    /// Parse TOML content (simple parser)
    fn parse_toml(content: &str) -> Option<Self> {
        let mut in_tool_velo = false;
        let mut config = Self::default();
        let mut found = false;

        for line in content.lines() {
            let line = line.trim();
            if line.starts_with('[') {
                in_tool_velo = line == "[tool.velo]";
                continue;
            }
            if !in_tool_velo {
                continue;
            }

            if let Some((key, value)) = line.split_once('=') {
                let key = key.trim();
                let value = value.trim();
                found = true;

                match key {
                    "preload" => {
                        if value.starts_with('[') && value.ends_with(']') {
                            config.preload = Self::parse_string_array(&value[1..value.len() - 1]);
                        }
                    }
                    "max_bundle_size" => {
                        if let Ok(mb) = value.parse::<usize>() {
                            config.max_bundle_size = mb * 1024 * 1024;
                        }
                    }
                    "zygote_socket_timeout" => {
                        if let Ok(secs) = value.parse::<u64>() {
                            config.zygote_socket_timeout = secs;
                        }
                    }
                    "slow_threshold_ms" => {
                        if let Ok(ms) = value.parse::<u64>() {
                            config.slow_threshold_ms = ms;
                        }
                    }
                    "security_trusted_prefixes" => {
                        if value.starts_with('[') {
                            config.security_trusted_prefixes =
                                Self::parse_string_array(&value[1..value.len() - 1]);
                        } else {
                            config.security_trusted_prefixes = Self::parse_string_array(value);
                        }
                    }
                    "security_env_whitelist" => {
                        if value.starts_with('[') {
                            config.security_env_whitelist =
                                Self::parse_string_array(&value[1..value.len() - 1]);
                        } else {
                            config.security_env_whitelist = Self::parse_string_array(value);
                        }
                    }
                    "security_hpc_threads" => {
                        if let Ok(n) = value.parse::<usize>() {
                            config.security_hpc_threads = n;
                        }
                    }
                    _ => {}
                }
            }
        }

        if found { Some(config) } else { None }
    }

    fn parse_string_array(s: &str) -> Vec<String> {
        s.split(',')
            .filter_map(|item| {
                let trimmed = item.trim().trim_matches('"').trim_matches('\'');
                if !trimmed.is_empty() {
                    Some(trimmed.to_string())
                } else {
                    None
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_toml_basic() {
        let content = r#"
[tool.velo]
preload = ["fastapi", "pydantic"]
max_bundle_size = 512
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.preload, vec!["fastapi", "pydantic"]);
        assert_eq!(config.max_bundle_size, 512 * 1024 * 1024);
    }

    #[test]
    fn test_security_profile_selection() {
        // Test PROD profile
        unsafe {
            std::env::set_var("VELO_ENV", "prod");
        }
        let config_prod = VeloConfig::default();
        // Prod should only have base + OS_BASE + CWD
        assert!(
            config_prod
                .security_trusted_prefixes
                .contains(&"/usr".to_string())
        );
        // On macOS, ${OS_BASE} includes Homebrew. On Linux, it would not.
        #[cfg(target_os = "macos")]
        assert!(
            config_prod
                .security_trusted_prefixes
                .contains(&"/opt/homebrew".to_string())
        );
        #[cfg(target_os = "linux")]
        assert!(
            !config_prod
                .security_trusted_prefixes
                .contains(&"/opt/homebrew".to_string())
        );

        // Test DEV profile
        unsafe {
            std::env::set_var("VELO_ENV", "dev");
        }
        let config_dev = VeloConfig::default();
        // Dev should have ${HOME} placeholder (after expansion)
        // Check for a known OS-specific path
        #[cfg(target_os = "macos")]
        assert!(
            config_dev
                .security_trusted_prefixes
                .contains(&"/opt/homebrew".to_string())
        );
        #[cfg(target_os = "linux")]
        assert!(
            config_dev
                .security_trusted_prefixes
                .contains(&"/lib64".to_string())
        );

        unsafe {
            std::env::remove_var("VELO_ENV");
        }
    }
}
