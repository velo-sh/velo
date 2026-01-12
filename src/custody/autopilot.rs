//! Zygote Autopilot - Intelligent Zygote lifecycle management (RFC-0018)
//!
//! This module implements heuristic-based automatic Zygote activation:
//! - Static Analysis Trigger (SAT): Detect heavy imports like torch, pandas
//! - Performance-Based Trigger (PBT): Track cold start times

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use serde::{Deserialize, Serialize};

#[cfg(unix)]
use fs2::FileExt;

/// Modules that trigger automatic Zygote activation
#[derive(Debug, Clone)]
pub struct GravityModule {
    /// Module name (e.g., "torch")
    pub name: &'static str,
    /// Weight for triggering (0.0 - 1.0, higher = more likely to trigger)
    pub weight: f32,
}

/// Known heavy modules that benefit from Zygote pre-warming
pub const GRAVITY_MODULES: &[GravityModule] = &[
    GravityModule {
        name: "torch",
        weight: 1.0,
    },
    GravityModule {
        name: "tensorflow",
        weight: 1.0,
    },
    GravityModule {
        name: "transformers",
        weight: 0.9,
    },
    GravityModule {
        name: "pandas",
        weight: 0.8,
    },
    GravityModule {
        name: "numpy",
        weight: 0.5,
    },
    GravityModule {
        name: "sklearn",
        weight: 0.7,
    },
    GravityModule {
        name: "scipy",
        weight: 0.6,
    },
    GravityModule {
        name: "jax",
        weight: 1.0,
    },
    GravityModule {
        name: "keras",
        weight: 0.9,
    },
];

/// Autopilot decision result
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AutopilotDecision {
    /// Don't use Zygote
    Disabled,
    /// Use Zygote based on static analysis
    EnabledByStatic { modules: Vec<String> },
    /// Use Zygote based on performance history
    EnabledByPerformance { avg_cold_start_ms: u64 },
    /// User explicitly requested
    EnabledByUser,
}

/// Autopilot heuristic engine
pub struct AutopilotEngine {
    /// Threshold for cumulative weight to trigger Zygote
    weight_threshold: f32,
    /// Threshold for cold start time (ms) to trigger PBT
    cold_start_threshold_ms: u64,
    /// Number of consecutive slow starts to trigger PBT
    slow_start_count: usize,
}

impl Default for AutopilotEngine {
    fn default() -> Self {
        Self {
            weight_threshold: 0.8,
            cold_start_threshold_ms: 500,
            slow_start_count: 3,
        }
    }
}

impl AutopilotEngine {
    /// Create engine with custom thresholds
    pub fn new(
        weight_threshold: f32,
        cold_start_threshold_ms: u64,
        slow_start_count: usize,
    ) -> Self {
        Self {
            weight_threshold,
            cold_start_threshold_ms,
            slow_start_count,
        }
    }

    /// Analyze a Python file for heavy imports (Static Analysis Trigger)
    pub fn analyze_imports(&self, script_path: &Path) -> AutopilotDecision {
        let content = match fs::read_to_string(script_path) {
            Ok(c) => c,
            Err(_) => return AutopilotDecision::Disabled,
        };

        let mut detected_modules = Vec::new();
        let mut cumulative_weight = 0.0f32;

        for module in GRAVITY_MODULES {
            // RFC-0018 Phase 7.1: Strict static analysis (DEF-71-009)
            // Use word-boundary regex and scan line-by-line to avoid comments/strings
            let patterns = [
                format!(
                    r"(?m)^[ \t]*import[ \t]+{}(?:[ \t]+|$)",
                    regex::escape(module.name)
                ),
                format!(
                    r"(?m)^[ \t]*from[ \t]+{}[ \t]+import",
                    regex::escape(module.name)
                ),
            ];

            for pattern in patterns {
                if matches!(regex::Regex::new(&pattern), Ok(re) if re.is_match(&content)) {
                    detected_modules.push(module.name.to_string());
                    cumulative_weight = cumulative_weight.max(module.weight);
                    break;
                }
            }
        }

        if cumulative_weight >= self.weight_threshold {
            AutopilotDecision::EnabledByStatic {
                modules: detected_modules,
            }
        } else {
            AutopilotDecision::Disabled
        }
    }

    /// Check performance history (Performance-Based Trigger)
    pub fn check_performance(&self, script_path: &Path) -> AutopilotDecision {
        let telemetry = TelemetryStore::load();

        if let Some(history) = telemetry.get_script_history(script_path) {
            // Check if recent cold starts exceed threshold
            let recent_slow: Vec<_> = history
                .cold_starts
                .iter()
                .rev()
                .take(self.slow_start_count)
                .filter(|&ms| *ms >= self.cold_start_threshold_ms)
                .collect();

            if recent_slow.len() >= self.slow_start_count {
                let avg = recent_slow.iter().copied().sum::<u64>() / recent_slow.len() as u64;
                return AutopilotDecision::EnabledByPerformance {
                    avg_cold_start_ms: avg,
                };
            }
        }

        AutopilotDecision::Disabled
    }

    /// Combined decision: SAT first, then PBT fallback
    pub fn should_use_zygote(&self, script_path: &Path) -> AutopilotDecision {
        // 1. Static Analysis Trigger (fast)
        let sat_result = self.analyze_imports(script_path);
        if sat_result != AutopilotDecision::Disabled {
            return sat_result;
        }

        // 2. Performance-Based Trigger (from telemetry)
        self.check_performance(script_path)
    }
}

/// Telemetry store for performance tracking
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TelemetryStore {
    /// Cold start times keyed by script path hash
    scripts: HashMap<String, ScriptHistory>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScriptHistory {
    /// Recent cold start times in milliseconds
    pub cold_starts: Vec<u64>,
    /// Last modification time of script
    pub last_modified: u64,
    /// Whether autopilot is enabled for this script
    pub auto_accelerate: bool,
}

impl TelemetryStore {
    fn telemetry_path() -> PathBuf {
        dirs::home_dir()
            .map(|h| h.join(".velo").join("telemetry.json"))
            .unwrap_or_else(|| PathBuf::from("/tmp/.velo/telemetry.json"))
    }

    /// Load telemetry from disk with advisory shared locking (DEF-71-007)
    pub fn load() -> Self {
        let path = Self::telemetry_path();
        if !path.exists() {
            return Self::default();
        }

        let lock_path = path.with_extension("lock");
        let lock_file = fs::OpenOptions::new()
            .read(true)
            .create(true)
            .append(true) // DEF-71-007: Open for advisory locking (no truncate needed)
            .open(&lock_path);

        if let Ok(file) = lock_file {
            #[cfg(unix)]
            let _ = file.lock_shared();

            let result = fs::read_to_string(&path)
                .ok()
                .and_then(|c| serde_json::from_str(&c).ok())
                .unwrap_or_default();

            #[cfg(unix)]
            let _ = file.unlock();

            result
        } else {
            Self::default()
        }
    }

    /// Save telemetry to disk with advisory file locking (DEF-71-007)
    pub fn save(&self) -> std::io::Result<()> {
        let path = Self::telemetry_path();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }

        let lock_path = path.with_extension("lock");
        let lock_file = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true) // DEF-71-007: Ensure clean lock file for exclusive access
            .open(&lock_path)?;

        #[cfg(unix)]
        {
            lock_file.lock_exclusive()?;

            let content = serde_json::to_string_pretty(self)?;
            let result = fs::write(&path, content);

            let _ = lock_file.unlock();
            result
        }

        #[cfg(not(unix))]
        {
            let content = serde_json::to_string_pretty(self)?;
            fs::write(&path, content)
        }
    }

    /// Get history for a script
    pub fn get_script_history(&self, script_path: &Path) -> Option<&ScriptHistory> {
        let key = Self::path_key(script_path);
        self.scripts.get(&key)
    }

    /// Record a cold start time
    pub fn record_cold_start(&mut self, script_path: &Path, duration_ms: u64) {
        let key = Self::path_key(script_path);

        let modified = fs::metadata(script_path)
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let history = self.scripts.entry(key).or_insert_with(|| ScriptHistory {
            cold_starts: Vec::new(),
            last_modified: modified,
            auto_accelerate: false,
        });

        // If script was modified, reset history
        if history.last_modified != modified {
            history.cold_starts.clear();
            history.last_modified = modified;
            history.auto_accelerate = false;
        }

        // Keep only last 10 entries
        if history.cold_starts.len() >= 10 {
            history.cold_starts.remove(0);
        }
        history.cold_starts.push(duration_ms);

        // Auto-mark for acceleration if consistently slow
        if history.cold_starts.len() >= 3 {
            let recent_slow = history
                .cold_starts
                .iter()
                .rev()
                .take(3)
                .filter(|&&ms| ms >= 500)
                .count();
            history.auto_accelerate = recent_slow >= 3;
        }
    }

    fn path_key(path: &Path) -> String {
        let hash = blake3::hash(path.to_string_lossy().as_bytes());
        hash.to_hex()[..16].to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_gravity_modules_defined() {
        assert!(!GRAVITY_MODULES.is_empty());
        assert!(GRAVITY_MODULES.iter().any(|m| m.name == "torch"));
    }

    #[test]
    fn test_analyze_imports_detects_torch() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test.py");
        fs::write(&script, "import torch\nx = torch.tensor([1,2,3])").unwrap();

        let engine = AutopilotEngine::default();
        let decision = engine.analyze_imports(&script);

        match decision {
            AutopilotDecision::EnabledByStatic { modules } => {
                assert!(modules.contains(&"torch".to_string()));
            }
            _ => panic!("Expected EnabledByStatic"),
        }
    }

    #[test]
    fn test_analyze_imports_detects_from_import() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test.py");
        fs::write(&script, "from transformers import AutoModel").unwrap();

        let engine = AutopilotEngine::default();
        let decision = engine.analyze_imports(&script);

        match decision {
            AutopilotDecision::EnabledByStatic { modules } => {
                assert!(modules.contains(&"transformers".to_string()));
            }
            _ => panic!("Expected EnabledByStatic"),
        }
    }

    #[test]
    fn test_analyze_imports_light_script() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test.py");
        fs::write(&script, "import os\nprint('hello')").unwrap();

        let engine = AutopilotEngine::default();
        let decision = engine.analyze_imports(&script);

        assert_eq!(decision, AutopilotDecision::Disabled);
    }

    #[test]
    fn test_analyze_imports_ignores_comments() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test_comments.py");
        fs::write(
            &script,
            "# import torch\n# from pandas import DataFrame\nprint('hello')",
        )
        .unwrap();

        let engine = AutopilotEngine::default();
        let decision = engine.analyze_imports(&script);

        assert_eq!(decision, AutopilotDecision::Disabled);
    }

    #[test]
    fn test_analyze_imports_detects_indented() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test_indent.py");
        fs::write(&script, "if True:\n    import torch").unwrap();

        let engine = AutopilotEngine::default();
        let decision = engine.analyze_imports(&script);

        match decision {
            AutopilotDecision::EnabledByStatic { modules } => {
                assert!(modules.contains(&"torch".to_string()));
            }
            _ => panic!("Expected EnabledByStatic for indented import"),
        }
    }

    #[test]
    fn test_telemetry_record_and_retrieve() {
        let tmp = tempdir().unwrap();
        let script = tmp.path().join("test.py");
        fs::write(&script, "print('test')").unwrap();

        let mut store = TelemetryStore::default();
        store.record_cold_start(&script, 600);
        store.record_cold_start(&script, 550);
        store.record_cold_start(&script, 580);

        let history = store.get_script_history(&script).unwrap();
        assert_eq!(history.cold_starts.len(), 3);
        assert!(history.auto_accelerate);
    }
}
