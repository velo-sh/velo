//! Velo configuration from pyproject.toml
//!
//! Parses [tool.velo] section for runtime configuration.
//!
//! ```toml
//! [tool.velo]
//! preload = ["fastapi", "pydantic", "uvicorn"]
//! ```

use std::path::Path;

/// Velo configuration
#[derive(Debug, Default, Clone)]
pub struct VeloConfig {
    /// Modules to preload in Zygote
    pub preload: Vec<String>,
    /// Maximum bundle size in Bytes
    pub max_bundle_size: Option<u64>,
    /// Zygote worker timeout in seconds
    pub zygote_worker_timeout: Option<u64>,
    /// Zygote socket startup timeout in seconds
    pub zygote_socket_timeout: Option<u64>,
}

impl VeloConfig {
    /// Read from pyproject.toml in current directory
    pub fn from_pyproject_toml() -> Option<Self> {
        Self::from_path(Path::new("pyproject.toml"))
    }

    /// Read from specific path
    pub fn from_path(path: &Path) -> Option<Self> {
        let content = std::fs::read_to_string(path).ok()?;
        Self::parse_toml(&content)
    }

    /// Parse TOML content (simple parser to avoid full toml dependency)
    #[allow(clippy::collapsible_if)]
    fn parse_toml(content: &str) -> Option<Self> {
        let mut in_tool_velo = false;
        let mut preload = Vec::new();
        let mut max_bundle_size = None;
        let mut zygote_worker_timeout = None;
        let mut zygote_socket_timeout = None;

        for line in content.lines() {
            let line = line.trim();

            // Check for section headers
            if line.starts_with('[') {
                in_tool_velo = line == "[tool.velo]";
                continue;
            }

            if !in_tool_velo {
                continue;
            }

            // Parse preload = [...] or preload = [...]
            if line.starts_with("preload") {
                if let Some(value_start) = line.find('[') {
                    if let Some(value_end) = line.find(']') {
                        let array_content = &line[value_start + 1..value_end];
                        preload = Self::parse_string_array(array_content);
                    }
                }
            } else if line.starts_with("max_bundle_size") {
                if let Some(eq_idx) = line.find('=') {
                    let value_str = line[eq_idx + 1..].trim();
                    // Parse numeric value (MB) and convert to Bytes
                    if let Ok(mb) = value_str.parse::<u64>() {
                        max_bundle_size = Some(mb * 1024 * 1024);
                    }
                }
            } else if line.starts_with("zygote_worker_timeout") {
                if let Some(eq_idx) = line.find('=') {
                    let value_str = line[eq_idx + 1..].trim();
                    if let Ok(secs) = value_str.parse::<u64>() {
                        zygote_worker_timeout = Some(secs);
                    }
                }
            } else if line.starts_with("zygote_socket_timeout") {
                if let Some(eq_idx) = line.find('=') {
                    let value_str = line[eq_idx + 1..].trim();
                    if let Ok(secs) = value_str.parse::<u64>() {
                        zygote_socket_timeout = Some(secs);
                    }
                }
            }
        }

        if preload.is_empty()
            && max_bundle_size.is_none()
            && zygote_worker_timeout.is_none()
            && zygote_socket_timeout.is_none()
        {
            None
        } else {
            Some(Self {
                preload,
                max_bundle_size,
                zygote_worker_timeout,
                zygote_socket_timeout,
            })
        }
    }

    /// Parse a simple string array like "fastapi", "pydantic"
    fn parse_string_array(s: &str) -> Vec<String> {
        s.split(',')
            .filter_map(|item| {
                let trimmed = item.trim();
                // Remove quotes
                if (trimmed.starts_with('"') && trimmed.ends_with('"'))
                    || (trimmed.starts_with('\'') && trimmed.ends_with('\''))
                {
                    Some(trimmed[1..trimmed.len() - 1].to_string())
                } else if !trimmed.is_empty() {
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
    fn test_parse_toml_with_preload() {
        let content = r#"
[project]
name = "myapp"

[tool.velo]
preload = ["fastapi", "pydantic", "uvicorn"]

[tool.other]
foo = "bar"
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.preload, vec!["fastapi", "pydantic", "uvicorn"]);
    }

    #[test]
    fn test_parse_toml_single_quotes() {
        let content = r#"
[tool.velo]
preload = ['numpy', 'pandas']
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.preload, vec!["numpy", "pandas"]);
    }

    #[test]
    fn test_parse_toml_no_tool_velo() {
        let content = r#"
[project]
name = "myapp"
"#;
        let config = VeloConfig::parse_toml(content);
        assert!(config.is_none());
    }

    #[test]
    fn test_parse_string_array() {
        let result = VeloConfig::parse_string_array(r#""fastapi", "pydantic""#);
        assert_eq!(result, vec!["fastapi", "pydantic"]);
    }

    #[test]
    fn test_parse_toml_max_bundle_size() {
        let content = r#"
[tool.velo]
max_bundle_size = 512
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.max_bundle_size, Some(512 * 1024 * 1024));
    }

    #[test]
    fn test_parse_toml_invalid_max_bundle_size() {
        let content = r#"
[tool.velo]
max_bundle_size = "not a number"
"#;
        let config = VeloConfig::parse_toml(content);
        // If preload is also missing, it returns None
        assert!(config.is_none());

        let content_with_preload = r#"
[tool.velo]
preload = ["fastapi"]
max_bundle_size = -5
"#;
        let config = VeloConfig::parse_toml(content_with_preload).unwrap();
        assert!(config.max_bundle_size.is_none());
        assert_eq!(config.preload, vec!["fastapi"]);
    }

    #[test]
    fn test_parse_toml_with_zygote_timeouts() {
        let content = r#"
[tool.velo]
zygote_worker_timeout = 60
zygote_socket_timeout = 20
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.zygote_worker_timeout, Some(60));
        assert_eq!(config.zygote_socket_timeout, Some(20));
    }
}
