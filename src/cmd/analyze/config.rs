//! Configuration parsing for `velo analyze` command.
//!
//! Parses [tool.velo] section from pyproject.toml.

use std::path::Path;

/// Configuration from pyproject.toml [tool.velo] section
#[derive(Debug, Clone, Default)]
pub struct VeloConfig {
    /// Modules to preload
    pub preload: Vec<String>,
    /// Custom slow threshold in ms
    pub slow_threshold_ms: Option<u64>,
}

impl VeloConfig {
    /// Read [tool.velo] configuration from pyproject.toml
    pub fn from_project(project_dir: &Path) -> Option<Self> {
        let pyproject_path = project_dir.join("pyproject.toml");
        if !pyproject_path.exists() {
            return None;
        }

        let content = std::fs::read_to_string(&pyproject_path).ok()?;
        Self::parse_toml(&content)
    }

    /// Parse [tool.velo] section from TOML content
    pub fn parse_toml(content: &str) -> Option<Self> {
        // Simple TOML parsing for [tool.velo] section
        // We avoid adding a full TOML parser dependency
        let mut in_tool_velo = false;
        let mut config = VeloConfig::default();

        for line in content.lines() {
            let trimmed = line.trim();

            // Check for section headers
            if trimmed.starts_with('[') {
                in_tool_velo = trimmed == "[tool.velo]";
                continue;
            }

            if !in_tool_velo {
                continue;
            }

            // Parse key = value pairs
            if let Some((key, value)) = trimmed.split_once('=') {
                let key = key.trim();
                let value = value.trim();

                match key {
                    "preload" => {
                        // Parse array: ["mod1", "mod2"]
                        config.preload = parse_string_array(value);
                    }
                    "slow_threshold_ms" => {
                        config.slow_threshold_ms = value.parse().ok();
                    }
                    _ => {}
                }
            }
        }

        if config.preload.is_empty() && config.slow_threshold_ms.is_none() {
            None
        } else {
            Some(config)
        }
    }
}

/// Parse a TOML-like string array: ["a", "b", "c"]
pub fn parse_string_array(s: &str) -> Vec<String> {
    let s = s.trim();
    if !s.starts_with('[') || !s.ends_with(']') {
        return vec![];
    }

    let inner = &s[1..s.len() - 1];
    inner
        .split(',')
        .map(|item| item.trim().trim_matches('"').trim_matches('\'').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_string_array() {
        assert_eq!(
            parse_string_array(r#"["numpy", "pandas"]"#),
            vec!["numpy", "pandas"]
        );
        assert_eq!(parse_string_array(r#"["single"]"#), vec!["single"]);
        assert_eq!(parse_string_array("[]"), Vec::<String>::new());
        assert_eq!(parse_string_array("invalid"), Vec::<String>::new());
    }

    #[test]
    fn test_velo_config_parse_toml() {
        let content = r#"
[project]
name = "test"

[tool.velo]
preload = ["numpy", "pandas"]
slow_threshold_ms = 50
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.preload, vec!["numpy", "pandas"]);
        assert_eq!(config.slow_threshold_ms, Some(50));
    }

    #[test]
    fn test_velo_config_parse_toml_no_section() {
        let content = r#"
[project]
name = "test"
"#;
        let config = VeloConfig::parse_toml(content);
        assert!(config.is_none());
    }

    #[test]
    fn test_velo_config_parse_toml_empty_preload() {
        let content = r#"
[tool.velo]
slow_threshold_ms = 75
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert!(config.preload.is_empty());
        assert_eq!(config.slow_threshold_ms, Some(75));
    }
}
