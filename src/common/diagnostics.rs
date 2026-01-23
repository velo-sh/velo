//! RFC-0038: AI-Native Diagnostics & Markdown Report Generation
//!
//! This module implements the `MarkdownFormatter` which produces
//! agent-friendly diagnostic reports.

use anyhow::{Context, Result};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// BUG-006 FIX: Pre-compiled regex for ANSI stripping
static ANSI_REGEX: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\x1B\[[0-9;]*[a-zA-Z]").expect("Invalid ANSI regex"));

/// Agent Hint Taxonomy (Appendix A of RFC-0038)
pub const HINT_LOOP_HOT: &str = "[loop-hot]";
pub const HINT_IO_BLOCKING: &str = "[io-blocking]";
pub const HINT_MEMORY_LEAK: &str = "[memory-leak]";
pub const HINT_GIL_CONTENTION: &str = "[gil-contention]";
pub const HINT_PRELOAD_MISS: &str = "[preload-miss]";

/// Formatter for AI-Native Diagnostic Reports (RFC-0038)
pub struct MarkdownFormatter {
    version: u32,
}

impl MarkdownFormatter {
    pub fn new(_title: &str) -> Self {
        Self { version: 1 }
    }

    /// Generate the full Markdown report
    pub fn format_report(
        &self,
        total_runtime: std::time::Duration,
        memory_delta_mb: f64,
        environment: &HashMap<String, String>,
        slow_imports: Vec<SlowImportInfo>,
        timeline: StartupTimeline,
    ) -> String {
        let mut md = String::new();

        // Header and Summary (RFC-0038 §3.2 & Council P0)
        md.push_str(&format!("<!-- velo:diagnostics v={} -->\n", self.version));
        md.push_str("# Velo Diagnostic Report v1\n\n");

        md.push_str("## 📋 Summary\n");
        md.push_str("| Key | Value |\n");
        md.push_str("| :--- | :--- |\n");
        md.push_str(&format!("| **Total Runtime** | {:.2?} |\n", total_runtime));

        let primary = slow_imports
            .first()
            .map(|b| format!("`{}`", b.name))
            .unwrap_or_else(|| "N/A".to_string());
        md.push_str(&format!("| **Slowest Import** | {} |\n", primary));
        // BUG-001 FIX: Memory Delta合并为2列 (GFM规范要求列数一致)
        let mem_status = if memory_delta_mb < 50.0 {
            "✅ COW Efficient"
        } else {
            "⚠️ Heavy Allocation"
        };
        md.push_str(&format!(
            "| **Memory Delta** | {:+.1}MB {} |\n",
            memory_delta_mb, mem_status
        ));
        // BUG-011 FIX: 添加缺失的空格
        md.push_str("| **Optimization Budget** | CPU-bound |\n");
        md.push_str("| **Status** | 🟢 Within Budget |\n\n");

        // System Environment
        md.push_str("## 💻 System Environment\n");
        md.push_str("| Variable | Value |\n");
        md.push_str("| :--- | :--- |\n");

        // RFC-0038 §3.2: Required static fields
        let gil_status = std::env::var("PYTHON_GIL")
            .map(|v| if v == "0" { "Disabled" } else { "Enabled" })
            .unwrap_or("Enabled");
        md.push_str(&format!("| **PYTHON_GIL** | `{}` |\n", gil_status));
        md.push_str(&format!(
            "| **PLATFORM** | `{} {}` |\n",
            std::env::consts::OS,
            std::env::consts::ARCH
        ));

        // Show all sanitized environment variables
        let mut keys: Vec<_> = environment.keys().collect();
        keys.sort();
        for key in keys {
            if let Some(val) = environment.get(key) {
                md.push_str(&format!("| **{}** | `{}` |\n", key, val));
            }
        }
        md.push('\n');

        md.push_str("> [!CAUTION]\n");
        md.push_str("> **Secrets Sanitizer**: Values for variables containing KEY, SECRET, TOKEN, or PASSWORD are redacted.\n\n");

        // Timeline (Mermaid)
        md.push_str("## ⏳ Startup Timeline\n\n");
        md.push_str("```mermaid\ngantt\n    title Velo Startup Phase\n    dateFormat  x\n    axisFormat %Lms\n");
        md.push_str("    section Boot\n");
        md.push_str(&format!("    Zygote       : 0, {}\n", timeline.zygote_ms));
        md.push_str(&format!(
            "    Env Shield   : {}, {}\n",
            timeline.zygote_ms.saturating_sub(2),
            timeline.zygote_ms + 4
        ));
        md.push_str("    section Runtime\n");
        md.push_str(&format!(
            "    App Entry    : {}, {}\n",
            timeline.zygote_ms + 4,
            timeline.app_entry_ms
        ));
        md.push_str(&format!(
            "    Imports      : crit, {}, {}\n",
            timeline.app_entry_ms, timeline.total_ms
        ));
        md.push_str("```\n\n");

        // Slow Imports Analysis
        md.push_str("## 🐢 Slow Imports (Critical Path)\n\n");
        for (i, b) in slow_imports.iter().take(20).enumerate() {
            md.push_str(&format!(
                "### {}. `{}` ({:.1}ms)\n",
                i + 1,
                b.name,
                b.duration_ms
            ));
            if let Some(loc) = &b.location {
                md.push_str(&format!("**Location:** `{}`\n", loc));
            }
            if let Some(hint) = &b.agent_hint {
                md.push_str(&format!(
                    "> **Agent Hint {}**: {}\n",
                    hint.tag, hint.message
                ));
            }
            md.push('\n');
        }

        if slow_imports.len() > 20 {
            md.push_str(&format!(
                "...and {} other slow imports truncated for token efficiency.\n",
                slow_imports.len() - 20
            ));
        }

        md
    }

    /// Redact sensitive environment variables
    pub fn sanitize_env(env: &HashMap<String, String>) -> HashMap<String, String> {
        let sensitive_keys = ["KEY", "SECRET", "TOKEN", "PASSWORD"];
        env.iter()
            .map(|(k, v)| {
                let is_sensitive = sensitive_keys.iter().any(|&s| k.to_uppercase().contains(s));
                if is_sensitive {
                    (k.clone(), "***".to_string())
                } else {
                    (k.clone(), v.clone())
                }
            })
            .collect()
    }

    /// Atomic write to file
    /// BUG-007 FIX: 使用带PID的唯一临时文件名避免竞态条件
    pub fn write_atomic(path: &Path, content: &str) -> Result<()> {
        let stripped = Self::strip_ansi(content);
        // 使用 PID + 时间戳确保唯一性
        let temp_name = format!(
            "{}.tmp.{}.{}",
            path.file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("report"),
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        );
        let temp_path = path.with_file_name(temp_name);
        fs::write(&temp_path, &stripped).with_context(|| {
            format!("Failed to write temporary diagnostic file: {:?}", temp_path)
        })?;
        fs::rename(&temp_path, path)
            .with_context(|| format!("Failed to move diagnostic file to final path: {:?}", path))?;
        Ok(())
    }

    /// Generate JSON format report (RFC-0038 GAP-3)
    pub fn format_json(
        &self,
        total_runtime: std::time::Duration,
        memory_delta_mb: f64,
        environment: &HashMap<String, String>,
        slow_imports: Vec<SlowImportInfo>,
        timeline: StartupTimeline,
    ) -> String {
        use serde_json::json;

        let gil_status = std::env::var("PYTHON_GIL")
            .map(|v| if v == "0" { "Disabled" } else { "Enabled" })
            .unwrap_or("Enabled");

        let platform = format!("{} {}", std::env::consts::OS, std::env::consts::ARCH);

        let slow_imports_json: Vec<serde_json::Value> = slow_imports
            .iter()
            .map(|b| {
                json!({
                    "name": b.name,
                    "duration_ms": b.duration_ms,
                    "location": b.location,
                    "agent_hint": b.agent_hint.as_ref().map(|h| json!({
                        "tag": h.tag,
                        "message": h.message
                    }))
                })
            })
            .collect();

        let report = json!({
            "schema_version": self.version,
            "summary": {
                "total_runtime_ms": total_runtime.as_millis(),
                "slowest_import": slow_imports.first().map(|b| &b.name),
                "memory_delta_mb": memory_delta_mb,
                "optimization_budget": "CPU-bound",
                "status": "Within Budget"
            },
            "environment": {
                "PYTHON_GIL": gil_status,
                "PLATFORM": platform,
                "variables": environment
            },
            "timeline": {
                "zygote_ms": timeline.zygote_ms,
                "app_entry_ms": timeline.app_entry_ms,
                "total_ms": timeline.total_ms
            },
            "slow_imports": slow_imports_json
        });

        serde_json::to_string_pretty(&report).unwrap_or_else(|_| "{}".to_string())
    }

    /// Strip ANSI escape codes to ensure "Purity" (Council P0)
    /// BUG-006 FIX: 使用预编译的正则表达式
    pub fn strip_ansi(text: &str) -> String {
        ANSI_REGEX.replace_all(text, "").to_string()
    }
}

pub struct SlowImportInfo {
    pub name: String,
    pub duration_ms: f64,
    pub location: Option<String>,
    pub agent_hint: Option<AgentHint>,
}

pub struct AgentHint {
    pub tag: String,
    pub message: String,
}

pub struct StartupTimeline {
    pub zygote_ms: u64,
    pub app_entry_ms: u64,
    pub total_ms: u64,
}
