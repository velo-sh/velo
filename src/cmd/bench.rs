//! Performance benchmarking CLI
//!
//! RFC-0007: Local-first performance tracking
//!
//! Commands:
//! - velo bench: Run benchmarks
//! - velo bench --save: Save to history
//! - velo bench compare <commit>: Compare with baseline
//! - velo bench history: View trends

use anyhow::{Result, anyhow};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;

/// Benchmark result entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchEntry {
    /// Git commit hash (short)
    pub commit: String,
    /// ISO8601 timestamp
    pub date: String,
    /// Machine identifier
    pub machine: String,
    /// Benchmark name
    pub bench: String,
    /// Duration in nanoseconds
    pub value_ns: u64,
}

/// Get machine identifier
fn get_machine_id() -> String {
    // Simplified: just use hostname
    // Full version would include CPU and memory
    hostname::get()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_else(|_| "unknown".to_string())
}

/// Get current git commit (short hash)
fn get_git_commit() -> Result<String> {
    let output = Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .output()?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        Err(anyhow!("Failed to get git commit"))
    }
}

/// Get ISO8601 timestamp
fn get_timestamp() -> String {
    chrono::Utc::now().to_rfc3339()
}

/// History file path
fn history_path(project_dir: &Path) -> PathBuf {
    project_dir.join(".velo/bench/history.jsonl")
}

/// Load benchmark history
pub fn load_history(project_dir: &Path) -> Result<Vec<BenchEntry>> {
    let path = history_path(project_dir);
    if !path.exists() {
        return Ok(vec![]);
    }

    let content = std::fs::read_to_string(&path)?;
    let mut entries = Vec::new();

    for line in content.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let entry: BenchEntry = serde_json::from_str(line)?;
        entries.push(entry);
    }

    Ok(entries)
}

/// Append entry to history
pub fn save_entry(project_dir: &Path, entry: &BenchEntry) -> Result<()> {
    let path = history_path(project_dir);

    // Create directory if needed
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    // Append JSONL
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)?;

    writeln!(file, "{}", serde_json::to_string(entry)?)?;
    Ok(())
}

/// Run a single benchmark and return result in nanoseconds
fn run_benchmark(name: &str) -> Result<u64> {
    use std::time::Instant;

    // Built-in benchmarks
    match name {
        "blake3_4mb" => {
            let data = vec![0u8; 4 * 1024 * 1024];
            let start = Instant::now();
            for _ in 0..10 {
                let _ = blake3::hash(&data);
            }
            Ok(start.elapsed().as_nanos() as u64 / 10)
        }
        "module_lookup" => {
            // Simulate O(1) lookup
            use std::collections::HashMap;
            let mut map: HashMap<String, u64> = HashMap::new();
            for i in 0..1000 {
                map.insert(format!("module_{}", i), i);
            }

            let start = Instant::now();
            for _ in 0..10000 {
                let _ = map.get("module_500");
            }
            Ok(start.elapsed().as_nanos() as u64 / 10000)
        }
        _ => Err(anyhow!("Unknown benchmark: {}", name)),
    }
}

/// Format duration for display
fn format_duration(ns: u64) -> String {
    if ns >= 1_000_000_000 {
        format!("{:.2}s", ns as f64 / 1_000_000_000.0)
    } else if ns >= 1_000_000 {
        format!("{:.2}ms", ns as f64 / 1_000_000.0)
    } else if ns >= 1_000 {
        format!("{:.2}μs", ns as f64 / 1_000.0)
    } else {
        format!("{}ns", ns)
    }
}

/// Run all benchmarks
fn run_all_benchmarks() -> Vec<(String, u64)> {
    let benchmarks = ["blake3_4mb", "module_lookup"];
    let mut results = Vec::new();

    for name in benchmarks {
        match run_benchmark(name) {
            Ok(ns) => results.push((name.to_string(), ns)),
            Err(e) => eprintln!("  {} failed: {}", name, e),
        }
    }

    results
}

/// Display benchmark results
fn display_results(results: &[(String, u64)]) {
    println!();
    println!("Running benchmarks...");
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();

    for (name, ns) in results {
        println!("  {:20} {:>10}", name, format_duration(*ns));
    }
    println!();
}

/// Display comparison between two commits
fn display_comparison(
    current: &str,
    baseline: &str,
    current_results: &[(String, u64)],
    baseline_results: &[(String, u64)],
) {
    println!();
    println!(
        "Comparing: {} (current) vs {} (baseline)",
        current, baseline
    );
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();
    println!(
        "  {:20} {:>12} {:>12} {:>10}",
        "Benchmark", "Current", "Baseline", "Change"
    );
    println!("  {}", "─".repeat(56));

    let mut improved = 0;
    let mut regressed = 0;
    let mut unchanged = 0;

    for (name, current_ns) in current_results {
        if let Some((_, baseline_ns)) = baseline_results.iter().find(|(n, _)| n == name) {
            let change = (*current_ns as f64 - *baseline_ns as f64) / *baseline_ns as f64 * 100.0;
            let icon = if change < -5.0 {
                improved += 1;
                "🎉"
            } else if change > 5.0 {
                regressed += 1;
                "⚠️"
            } else {
                unchanged += 1;
                "✅"
            };

            println!(
                "  {:20} {:>12} {:>12} {:>+7.1}% {}",
                name,
                format_duration(*current_ns),
                format_duration(*baseline_ns),
                change,
                icon
            );
        }
    }

    println!();
    println!(
        "Summary: {} improved, {} unchanged, {} regressed",
        improved, unchanged, regressed
    );
}

/// Display history for a benchmark
fn display_history(entries: &[BenchEntry], bench_name: &str, limit: usize) {
    let filtered: Vec<_> = entries
        .iter()
        .filter(|e| e.bench == bench_name)
        .rev()
        .take(limit)
        .collect();

    if filtered.is_empty() {
        println!("No history for benchmark: {}", bench_name);
        return;
    }

    println!();
    println!("History: {} (last {} runs)", bench_name, limit);
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();
    println!("  {:10} {:12} {:>12}", "Commit", "Date", "Value");
    println!("  {}", "─".repeat(38));

    for entry in filtered {
        let date_short = entry.date.split('T').next().unwrap_or(&entry.date);
        println!(
            "  {:10} {:12} {:>12}",
            &entry.commit,
            date_short,
            format_duration(entry.value_ns)
        );
    }
}

/// Main bench command entry point
pub fn cmd_bench(args: &[String]) -> Result<()> {
    let project_dir = std::env::current_dir()?;

    // Parse arguments
    let save = args.iter().any(|a| a == "--save");
    let compare_idx = args.iter().position(|a| a == "compare");
    let history_idx = args.iter().position(|a| a == "history");

    if let Some(idx) = compare_idx {
        // velo bench compare <commit>
        let baseline = args
            .get(idx + 1)
            .ok_or_else(|| anyhow!("Usage: velo bench compare <commit>"))?;

        let history = load_history(&project_dir)?;
        let current_commit = get_git_commit()?;

        // Get baseline results from history
        let baseline_results: Vec<_> = history
            .iter()
            .filter(|e| e.commit.starts_with(baseline))
            .map(|e| (e.bench.clone(), e.value_ns))
            .collect();

        if baseline_results.is_empty() {
            return Err(anyhow!("No benchmark data for commit: {}", baseline));
        }

        // Run current benchmarks
        let current_results = run_all_benchmarks();

        display_comparison(
            &current_commit,
            baseline,
            &current_results,
            &baseline_results,
        );
        return Ok(());
    }

    if history_idx.is_some() {
        // velo bench history
        let history = load_history(&project_dir)?;
        display_history(&history, "blake3_4mb", 10);
        return Ok(());
    }

    // Default: run benchmarks
    let results = run_all_benchmarks();
    display_results(&results);

    if save {
        let commit = get_git_commit()?;
        let date = get_timestamp();
        let machine = get_machine_id();

        for (bench, value_ns) in &results {
            let entry = BenchEntry {
                commit: commit.clone(),
                date: date.clone(),
                machine: machine.clone(),
                bench: bench.clone(),
                value_ns: *value_ns,
            };
            save_entry(&project_dir, &entry)?;
        }

        println!("✅ Results saved to .velo/bench/history.jsonl");
        println!("   Commit: {} | Machine: {}", commit, machine);
    }

    Ok(())
}
