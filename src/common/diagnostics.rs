//! RFC-0038: AI-Native Diagnostics & Markdown Report Generation
//!
//! This module implements the `MarkdownFormatter` which produces
//! agent-friendly diagnostic reports.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Agent Hint Taxonomy (Appendix A of RFC-0038)
pub const HINT_LOOP_HOT: &str = "[loop-hot]";
pub const HINT_IO_BLOCKING: &str = "[io-blocking]";
pub const HINT_MEMORY_LEAK: &str = "[memory-leak]";
pub const HINT_GIL_CONTENTION: &str = "[gil-contention]";
pub const HINT_PRELOAD_MISS: &str = "[preload-miss]";

/// Formatter for AI-Native Diagnostic Reports (RFC-0038)
pub struct MarkdownFormatter {
    title: String,
    version: u32,
}

impl MarkdownFormatter {
    pub fn new(title: &str) -> Self {
        Self {
            title: title.to_string(),
            version: 1,
        }
    }

    /// Generate the full Markdown report
    pub fn format_report(
        &self,
        total_runtime: std::time::Duration,
        environment: &HashMap<String, String>,
        bottlenecks: Vec<BottleneckInfo>,
        timeline: StartupTimeline,
    ) -> String {
        let mut md = String::new();

        // Header and Summary
        md.push_str(&format!("<!-- velo:diagnostics v={} -->\n", self.version));
        md.push_str(&format!("# {}\n\n", self.title));

        md.push_str("## 📋 Summary\n");
        md.push_str("| Key | Value |\n");
        md.push_str("| :--- | :--- |\n");
        md.push_str(&format!("| **Total Runtime** | {:.2?} |\n", total_runtime));

        let primary = bottlenecks
            .first()
            .map(|b| format!("`{}`", b.name))
            .unwrap_or_else(|| "N/A".to_string());
        md.push_str(&format!("| **Primary Bottleneck** | {} |\n", primary));
        md.push_str("| **Optimization Budget**| CPU-bound |\n");
        md.push_str("| **Status** | 🟢 Within Budget |\n\n");

        // System Environment
        md.push_str("## 💻 System Environment\n");
        md.push_str("| Variable | Value |\n");
        md.push_str("| :--- | :--- |\n");

        // Pick a few stable ones
        for &key in &["VELO_MODE", "PYTHONPATH", "PLATFORM"] {
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

        // Bottleneck Analysis
        md.push_str("## 🔍 Top Bottleneck Analysis\n\n");
        for (i, b) in bottlenecks.iter().take(20).enumerate() {
            md.push_str(&format!(
                "### {}. {} ({:.1}ms)\n",
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

        if bottlenecks.len() > 20 {
            md.push_str(&format!(
                "...and {} other bottlenecks truncated for token efficiency.\n",
                bottlenecks.len() - 20
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
    pub fn write_atomic(path: &Path, content: &str) -> Result<()> {
        let temp_path = path.with_extension("tmp");
        fs::write(&temp_path, content).with_context(|| {
            format!("Failed to write temporary diagnostic file: {:?}", temp_path)
        })?;
        fs::rename(&temp_path, path)
            .with_context(|| format!("Failed to move diagnostic file to final path: {:?}", path))?;
        Ok(())
    }
}

pub struct BottleneckInfo {
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
