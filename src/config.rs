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
            }
        }

        if preload.is_empty() {
            None
        } else {
            Some(Self { preload })
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
}
