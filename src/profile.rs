//! Startup profiling for `velo run --profile`.
//!
//! Injects a sitecustomize.py that hooks into Python's import system
//! to track timing of all imports. Results are written to a temp file
//! and parsed by Velo to display a detailed startup breakdown.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Python code to inject as sitecustomize.py for profiling and preloading.
/// This hooks into builtins.__import__ to track import times and performs native preloading.
/// RFC-0038-ext: Extended to capture __file__ for code snippet extraction.
pub const SITECUSTOMIZE_PY: &str = r#"
import sys
import time
import json
import os
import builtins
import tempfile

# --- RFC-0035 Native Preloading Hook ---
def _v_activate_preloading():
    lock_json = os.environ.get("VELO_RUNTIME_PRELOAD_LOCK")
    if not lock_json:
        return
    try:
        # Try to use the isolated namespace first
        import __velo__
        __velo__.native_preload("PreInit")
    except ImportError:
        try:
            # Fallback to bootstrap if not initialized
            from velo_zygote import bootstrap
            bootstrap.initialize()
        except Exception as e:
            # LOP compliant error (approximate for early boot)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            sys.stderr.write(f"[{timestamp}] [STD] WARN [VELO-PRELOAD-FAIL] Native preload hook failed: {e}\n")

_v_activate_preloading()
# ---------------------------------------

_velo_import_data = {}
_velo_original_import = builtins.__import__

# RFC-0038-ext: Configurable threshold (default 1.0ms)
_VELO_IMPORT_THRESHOLD_MS = float(os.environ.get('VELO_IMPORT_THRESHOLD_MS', '1.0'))

def _velo_timed_import(name, *args, **kwargs):
    start = time.perf_counter()
    module = _velo_original_import(name, *args, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000  # ms
    
    if elapsed > _VELO_IMPORT_THRESHOLD_MS:
        if name not in _velo_import_data:
            file_path = getattr(module, '__file__', None)
            
            # RFC-0038-ext COMPAT-001: Skip namespace packages and frozen modules
            if file_path is not None and file_path.startswith('<'):
                file_path = None
            
            _velo_import_data[name] = {
                "elapsed_ms": elapsed,
                "file": file_path,
                "is_namespace": file_path is None
            }
    return module

builtins.__import__ = _velo_timed_import

def _velo_write_profile():
    default_path = os.path.join(tempfile.gettempdir(), 'velo_profile.json')
    output_path = os.environ.get('VELO_PROFILE_OUTPUT', default_path)
    try:
        with open(output_path, 'w') as f:
            json.dump(_velo_import_data, f)
    except:
        pass  # Best effort - don't fail on profile write error

# Register for normal exit
import atexit
atexit.register(_velo_write_profile)

# Also register for unhandled exceptions (ensures profile is written on crash)
_velo_original_excepthook = sys.excepthook
def _velo_excepthook(exc_type, exc_value, exc_tb):
    _velo_write_profile()
    _velo_original_excepthook(exc_type, exc_value, exc_tb)
sys.excepthook = _velo_excepthook
"#;

/// Parsed profile data from a profiled run.
#[derive(Debug, Clone)]
pub struct ProfileData {
    /// Module name -> import time in milliseconds
    pub import_times: HashMap<String, f64>,
    /// Module name -> file path (RFC-0038-ext: for code snippet extraction)
    pub import_files: HashMap<String, Option<String>>,
    /// Total import time
    pub total_import_time_ms: f64,
    /// Memory growth during execution (MB)
    pub memory_delta_mb: f64,
}

/// RFC-0038-ext: Import entry from Python hook
#[derive(Debug, Clone, serde::Deserialize)]
struct ImportEntry {
    elapsed_ms: f64,
    file: Option<String>,
    #[serde(default)]
    #[allow(dead_code)] // Captured from Python for future use
    is_namespace: bool,
}

impl ProfileData {
    /// Parse profile data from JSON file produced by sitecustomize.py.
    /// RFC-0038-ext: Now parses new format with file paths.
    pub fn from_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read profile file: {:?}", path))?;

        // Try new format first (dict of {elapsed_ms, file, is_namespace})
        if let Ok(import_entries) = serde_json::from_str::<HashMap<String, ImportEntry>>(&content) {
            let import_times: HashMap<String, f64> = import_entries
                .iter()
                .map(|(k, v)| (k.clone(), v.elapsed_ms))
                .collect();
            let import_files: HashMap<String, Option<String>> = import_entries
                .iter()
                .map(|(k, v)| (k.clone(), v.file.clone()))
                .collect();
            let total_import_time_ms = import_times.values().sum();

            return Ok(Self {
                import_times,
                import_files,
                total_import_time_ms,
                memory_delta_mb: 0.0,
            });
        }

        // Fallback: legacy format (dict of module -> time_ms)
        let import_times: HashMap<String, f64> =
            serde_json::from_str(&content).with_context(|| "Failed to parse profile JSON")?;

        let total_import_time_ms = import_times.values().sum();

        Ok(Self {
            import_times,
            import_files: HashMap::new(),
            total_import_time_ms,
            memory_delta_mb: 0.0,
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

    /// Get the top N slowest imports as SlowImportInfo.
    /// RFC-0038-ext: Now includes file paths and code snippets for top 5.
    pub fn to_slow_imports(&self, n: usize) -> Vec<crate::common::diagnostics::SlowImportInfo> {
        use crate::common::snippet_extractor::extract_snippets_parallel;
        use std::path::PathBuf;

        let mut imports: Vec<(&String, &f64)> = self.import_times.iter().collect();
        imports.sort_by(|a, b| b.1.partial_cmp(a.1).unwrap_or(std::cmp::Ordering::Equal));

        // Collect file paths for top N imports
        let file_paths: Vec<Option<PathBuf>> = imports
            .iter()
            .take(n)
            .map(|(name, _)| {
                self.import_files
                    .get(*name)
                    .and_then(|p| p.as_ref())
                    .map(PathBuf::from)
            })
            .collect();

        // Extract snippets in parallel (only top 5)
        let snippets = extract_snippets_parallel(&file_paths);

        imports
            .iter()
            .take(n)
            .enumerate()
            .map(|(i, (name, time))| {
                let file_path = file_paths.get(i).cloned().flatten();
                let code_snippet = snippets.get(i).cloned().flatten();

                crate::common::diagnostics::SlowImportInfo {
                    name: name.to_string(),
                    duration_ms: **time,
                    file_path,
                    location: get_module_location(name),
                    code_snippet,
                    agent_hint: get_optimization_suggestions(name).map(|msg| {
                        crate::common::diagnostics::AgentHint {
                            tag: crate::common::diagnostics::HINT_PRELOAD_MISS.to_string(),
                            message: msg.to_string(),
                        }
                    }),
                }
            })
            .collect()
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

/// Provide location hints for known heavy modules (RFC-0038 GAP-4).
pub fn get_module_location(module: &str) -> Option<String> {
    match module {
        "numpy" => Some("numpy/__init__.py (C-extension init)".to_string()),
        "pandas" => Some("pandas/__init__.py".to_string()),
        "torch" | "pytorch" => Some("torch/__init__.py (CUDA init)".to_string()),
        "tensorflow" => Some("tensorflow/__init__.py (GPU init)".to_string()),
        "django" => Some("django/__init__.py (apps registry)".to_string()),
        "fastapi" => Some("fastapi/__init__.py".to_string()),
        "sqlalchemy" => Some("sqlalchemy/__init__.py".to_string()),
        "scipy" => Some("scipy/__init__.py (C-extension)".to_string()),
        "sklearn" | "scikit-learn" => Some("sklearn/__init__.py".to_string()),
        "transformers" => Some("transformers/__init__.py (tokenizers)".to_string()),
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
        assert!(SITECUSTOMIZE_PY.contains("builtins.__import__"));
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
