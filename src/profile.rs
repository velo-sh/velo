//! Startup profiling for `velo run --profile`.
//!
//! Injects a sitecustomize.py that hooks into Python's import system
//! to track timing of all imports. Results are written to a temp file
//! and parsed by Velo to display a detailed startup breakdown.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Python code to inject as sitecustomize.py for profiling.
/// This hooks into __builtins__.__import__ to track import times.
pub const SITECUSTOMIZE_PY: &str = r#"
import sys
import time
import json
import os

_velo_import_times = {}
_velo_original_import = __builtins__.__import__

def _velo_timed_import(name, *args, **kwargs):
    start = time.perf_counter()
    result = _velo_original_import(name, *args, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000  # ms
    if elapsed > 0.5:  # Only track imports > 0.5ms
        if name not in _velo_import_times:
            _velo_import_times[name] = elapsed
    return result

__builtins__.__import__ = _velo_timed_import

import atexit
@atexit.register
def _velo_write_profile():
    output_path = os.environ.get('VELO_PROFILE_OUTPUT', '/tmp/velo_profile.json')
    with open(output_path, 'w') as f:
        json.dump(_velo_import_times, f)
"#;

/// Parsed profile data from a profiled run.
#[derive(Debug, Clone)]
pub struct ProfileData {
    /// Module name -> import time in milliseconds
    pub import_times: HashMap<String, f64>,
    /// Total import time
    pub total_import_time_ms: f64,
}

impl ProfileData {
    /// Parse profile data from JSON file produced by sitecustomize.py.
    pub fn from_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read profile file: {:?}", path))?;

        let import_times: HashMap<String, f64> =
            serde_json::from_str(&content).with_context(|| "Failed to parse profile JSON")?;

        let total_import_time_ms = import_times.values().sum();

        Ok(Self {
            import_times,
            total_import_time_ms,
        })
    }

    /// Get the top N slowest imports.
    pub fn top_imports(&self, n: usize) -> Vec<(&str, f64)> {
        let mut imports: Vec<(&str, f64)> = self
            .import_times
            .iter()
            .map(|(k, v)| (k.as_str(), *v))
            .collect();

        imports.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        imports.truncate(n);
        imports
    }

    /// Format profile as a table for display.
    pub fn format_table(&self, max_imports: usize) -> String {
        let mut output = String::new();

        output.push_str("┌──────────────────────────────────────────────────────────────┐\n");
        output.push_str("│                    Velo Startup Profile                      │\n");
        output.push_str("├──────────────────────────────────────────────────────────────┤\n");

        let top = self.top_imports(max_imports);
        let remaining_count = self.import_times.len().saturating_sub(max_imports);
        let remaining_time: f64 = if remaining_count > 0 {
            self.total_import_time_ms - top.iter().map(|(_, t)| t).sum::<f64>()
        } else {
            0.0
        };

        for (name, time_ms) in &top {
            let bar_len = ((time_ms / 100.0) * 20.0).min(20.0) as usize;
            let bar: String = "█".repeat(bar_len);
            output.push_str(&format!(
                "│ {:30} {:>7.1}ms │ {:20} │\n",
                truncate_string(name, 30),
                time_ms,
                bar
            ));
        }

        if remaining_count > 0 {
            output.push_str(&format!(
                "│ ({} more modules)               {:>7.1}ms │                      │\n",
                remaining_count, remaining_time
            ));
        }

        output.push_str("├──────────────────────────────────────────────────────────────┤\n");
        output.push_str(&format!(
            "│ TOTAL                           {:>7.1}ms │                      │\n",
            self.total_import_time_ms
        ));
        output.push_str("└──────────────────────────────────────────────────────────────┘\n");

        output
    }
}

/// Truncate a string to max characters, adding "..." if truncated.
fn truncate_string(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("{}...", &s[..max_len - 3])
    }
}

/// Known heavy modules with optimization suggestions.
pub fn get_optimization_suggestions(module: &str) -> Option<&'static str> {
    match module {
        "numpy" => Some("C-Extension. Consider Zygote pre-warming."),
        "pandas" => Some("Large dependency tree. Consider lazy import."),
        "torch" | "pytorch" => Some("GPU initialization. Use Zygote."),
        "tensorflow" => Some("GPU initialization. Use Zygote."),
        "django" => Some("App registry setup."),
        "fastapi" => Some("Middleware initialization."),
        "sqlalchemy" => Some("Dialect loading."),
        "scipy" => Some("C-Extension."),
        "sklearn" | "scikit-learn" => Some("Model loading."),
        "transformers" => Some("Tokenizer loading."),
        _ => None,
    }
}

// ============================================================================
// TESTS (TDD)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_sitecustomize_contains_import_hook() {
        assert!(SITECUSTOMIZE_PY.contains("_velo_timed_import"));
        assert!(SITECUSTOMIZE_PY.contains("__builtins__.__import__"));
        assert!(SITECUSTOMIZE_PY.contains("VELO_PROFILE_OUTPUT"));
    }

    #[test]
    fn test_profile_data_from_json() {
        let dir = tempdir().unwrap();
        let json_path = dir.path().join("profile.json");

        let json_content = r#"{"numpy": 68.3, "pandas": 52.1, "fastapi": 34.7}"#;
        fs::write(&json_path, json_content).unwrap();

        let profile = ProfileData::from_file(&json_path).unwrap();

        assert_eq!(profile.import_times.len(), 3);
        assert!((profile.import_times["numpy"] - 68.3).abs() < 0.01);
        assert!((profile.total_import_time_ms - 155.1).abs() < 0.01);
    }

    #[test]
    fn test_top_imports_sorted() {
        let dir = tempdir().unwrap();
        let json_path = dir.path().join("profile.json");

        let json_content = r#"{"a": 10.0, "b": 50.0, "c": 30.0, "d": 20.0}"#;
        fs::write(&json_path, json_content).unwrap();

        let profile = ProfileData::from_file(&json_path).unwrap();
        let top = profile.top_imports(2);

        assert_eq!(top.len(), 2);
        assert_eq!(top[0].0, "b"); // 50.0 - highest
        assert_eq!(top[1].0, "c"); // 30.0 - second
    }

    #[test]
    fn test_format_table() {
        let dir = tempdir().unwrap();
        let json_path = dir.path().join("profile.json");

        let json_content = r#"{"numpy": 68.3, "pandas": 52.1}"#;
        fs::write(&json_path, json_content).unwrap();

        let profile = ProfileData::from_file(&json_path).unwrap();
        let table = profile.format_table(5);

        assert!(table.contains("Velo Startup Profile"));
        assert!(table.contains("numpy"));
        assert!(table.contains("TOTAL"));
    }

    #[test]
    fn test_truncate_string() {
        assert_eq!(truncate_string("short", 10), "short");
        assert_eq!(truncate_string("verylongmodulename", 10), "verylon...");
    }

    #[test]
    fn test_optimization_suggestions() {
        assert!(get_optimization_suggestions("numpy").is_some());
        assert!(get_optimization_suggestions("pandas").is_some());
        assert!(get_optimization_suggestions("unknown_module").is_none());
    }
}
