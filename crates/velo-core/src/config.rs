//! Velo configuration logic (RFC-0012)
//!
//! Parses [tool.velo] section from pyproject.toml and applies environment overrides.

use crate::common::paths::VeloPaths;
use std::path::Path;

/// Embedded SSOT for runtime defaults
use velo_macros::generate_config;

generate_config!();

/// Public interface to extract path configuration (RFC-0012 Phase 6.5)
pub fn extract_path_config(key: &str) -> Option<String> {
    // Fallback to manual parsing for dynamic keys not baked into the macro
    for line in include_str!("../../../config/constants.toml").lines() {
        let line = line.trim();
        if line.starts_with(key)
            && let Some((_, val)) = line.split_once('=')
        {
            return Some(val.trim().trim_matches('"').to_string());
        }
    }
    None
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
        if let Ok(val) = std::env::var("VELO_NATIVE_PRELOAD") {
            self.native_libraries = Self::parse_string_array(&val);
        }
        if let Ok(val) = std::env::var("VELO_PATH_INTEGRITY") {
            let val = val.to_lowercase();
            if val == "enforce" || val == "warn" || val == "off" {
                self.path_integrity = val;
            }
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
        if let Some(secs) = std::env::var("VELO_GRACEFUL_SHUTDOWN_TIMEOUT")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
        {
            self.graceful_shutdown_timeout = secs;
        }
        if let Some(b) = std::env::var("VELO_STRICT_OPTIMIZATIONS")
            .ok()
            .and_then(|v| v.parse::<bool>().ok())
        {
            self.strict_optimizations = b;
        }
        if let Some(ms) = std::env::var("VELO_SLO_FORK_LATENCY_MS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
        {
            self.slo_fork_latency_ms = ms;
        }
        if let Ok(val) = std::env::var("VELO_ZYGOTE_AUTH") {
            self.forensic_secret = Some(val);
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
                    "native_libraries" => {
                        if value.starts_with('[') && value.ends_with(']') {
                            config.native_libraries =
                                Self::parse_string_array(&value[1..value.len() - 1]);
                        }
                    }
                    "path_integrity" => {
                        let v = value.trim_matches('"').to_lowercase();
                        if v == "enforce" || v == "warn" || v == "off" {
                            config.path_integrity = v;
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
                    "graceful_shutdown_timeout" => {
                        if let Ok(secs) = value.parse::<u64>() {
                            config.graceful_shutdown_timeout = secs;
                        }
                    }
                    "strict_optimizations" => {
                        if let Ok(b) = value.parse::<bool>() {
                            config.strict_optimizations = b;
                        }
                    }
                    "slo_fork_latency_ms" => {
                        if let Ok(ms) = value.parse::<u64>() {
                            config.slo_fork_latency_ms = ms;
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
