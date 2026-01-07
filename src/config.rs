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
}

impl Default for VeloConfig {
    fn default() -> Self {
        Self {
            preload: Vec::new(),
            max_bundle_size: 1024 * 1024 * 1024, // 1GB default
            zygote_socket_timeout: extract_default_u64("socket_startup_timeout", 5),
            slow_threshold_ms: extract_default_u64("default_slow_threshold_ms", 100),
        }
    }
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
}
