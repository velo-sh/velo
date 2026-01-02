//! Display formatting for `velo analyze` command.
//!
//! Provides visual bar charts and colored output for analysis results.

use super::config::VeloConfig;
use crate::profile::{ProfileData, get_optimization_suggestions};

/// ANSI color codes for terminal output
pub mod colors {
    pub const RESET: &str = "\x1b[0m";
    pub const BOLD: &str = "\x1b[1m";
    pub const RED: &str = "\x1b[31m";
    pub const GREEN: &str = "\x1b[32m";
    pub const YELLOW: &str = "\x1b[33m";
    pub const CYAN: &str = "\x1b[36m";
    pub const DIM: &str = "\x1b[2m";
}

/// Display analysis results with visual bar chart
pub fn display_analysis(profile: &ProfileData, threshold_ms: u64) {
    let top = profile.top_imports(15);
    let max_time = top.first().map(|(_, t)| *t).unwrap_or(1.0);

    println!();
    println!(
        "{}┌─────────────────────────────────────────────────────────────┐{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}│                    Import Analysis                          │{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );

    for (name, time_ms) in &top {
        let bar_width = ((time_ms / max_time) * 25.0) as usize;
        let bar: String = "█".repeat(bar_width);

        // Color based on threshold
        let (color, label) = if *time_ms >= threshold_ms as f64 {
            (colors::RED, " ← SLOW")
        } else if *time_ms >= (threshold_ms / 2) as f64 {
            (colors::YELLOW, "")
        } else {
            (colors::GREEN, "")
        };

        println!(
            "│ {:28} {:>7.1}ms │ {}{:25}{} {}│",
            truncate_str(name, 28),
            time_ms,
            color,
            bar,
            colors::RESET,
            label
        );
    }

    // Show remaining count
    let remaining = profile.import_times.len().saturating_sub(15);
    if remaining > 0 {
        let remaining_time: f64 =
            profile.total_import_time_ms - top.iter().map(|(_, t)| t).sum::<f64>();
        println!(
            "│ {}({} more modules){:>23.1}ms │                           │",
            colors::DIM,
            remaining,
            remaining_time,
        );
        print!("{}", colors::RESET);
    }

    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}│ TOTAL                           {:>7.1}ms │                           │{}",
        colors::BOLD,
        profile.total_import_time_ms,
        colors::RESET
    );
    println!(
        "{}└─────────────────────────────────────────────────────────────┘{}",
        colors::BOLD,
        colors::RESET
    );
}

/// Display preload suggestions based on slow imports
pub fn display_preload_suggestions(
    profile: &ProfileData,
    threshold_ms: u64,
    existing_config: Option<&VeloConfig>,
) {
    let slow_imports: Vec<_> = profile
        .import_times
        .iter()
        .filter(|(_, time)| **time >= threshold_ms as f64)
        .map(|(name, time)| (name.as_str(), *time))
        .collect();

    if slow_imports.is_empty() {
        println!(
            "\n{}✨ No slow imports detected (threshold: {}ms){}",
            colors::GREEN,
            threshold_ms,
            colors::RESET
        );
        return;
    }

    println!();
    println!(
        "{}💡 Optimization Suggestions:{}",
        colors::CYAN,
        colors::RESET
    );
    println!();

    // Sort by time descending
    let mut sorted = slow_imports;
    sorted.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Get top-level module names for preload
    let preload_modules: Vec<_> = sorted
        .iter()
        .map(|(name, _)| name.split('.').next().unwrap_or(name))
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();

    // Check which are already configured
    let already_preloaded: Vec<_> = if let Some(cfg) = existing_config {
        preload_modules
            .iter()
            .filter(|m| cfg.preload.iter().any(|p| p == **m))
            .cloned()
            .collect()
    } else {
        vec![]
    };

    let new_modules: Vec<_> = preload_modules
        .iter()
        .filter(|m| !already_preloaded.contains(m))
        .cloned()
        .collect();

    if !already_preloaded.is_empty() {
        println!(
            "  {}✓ Already in preload:{} {:?}",
            colors::GREEN,
            colors::RESET,
            already_preloaded
        );
    }

    if !new_modules.is_empty() {
        println!(
            "  {}1. Add to preload:{} {:?}",
            colors::BOLD,
            colors::RESET,
            new_modules
        );
    }

    // Show specific suggestions for known modules
    println!();
    for (name, time) in &sorted {
        if let Some(suggestion) = get_optimization_suggestions(name) {
            println!(
                "  {}• {}{} ({:.1}ms): {}",
                colors::YELLOW,
                name,
                colors::RESET,
                time,
                suggestion
            );
        }
    }

    // Show config hint if there are new modules
    if !new_modules.is_empty() {
        println!();
        println!("  {}Add to pyproject.toml:{}", colors::DIM, colors::RESET);
        println!("  {}[tool.velo]{}", colors::DIM, colors::RESET);
        println!(
            "  {}preload = {:?}{}",
            colors::DIM,
            new_modules,
            colors::RESET
        );
    }
}

/// Truncate string with ellipsis
pub fn truncate_str(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        format!("{:width$}", s, width = max_len)
    } else {
        format!("{}...", &s[..max_len - 3])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_truncate_str() {
        assert_eq!(truncate_str("short", 10), "short     ");
        assert_eq!(truncate_str("verylongmodulename", 10), "verylon...");
    }
}
