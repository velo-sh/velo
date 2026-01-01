use anyhow::{Context, Result};
use pyo3::prelude::*;
use std::path::Path;

mod cache;
use cache::EnvCache;

/// Python home path discovered at compile time
const PYTHON_HOME: &str = env!("VELO_PYTHON_HOME");

const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run <script.py>

COMMANDS:
    run     Run a Python script

OPTIONS:
    -h, --help     Print help
    -V, --version  Print version
";

/// Setup Python environment before initializing the interpreter.
/// Uses cached configuration if available to speed up startup.
fn setup_python_env(project_dir: &Path) -> Option<EnvCache> {
    // Set PYTHONHOME
    if std::env::var("PYTHONHOME").is_err() {
        // SAFETY: set_var is called before any threads are spawned and before Python is initialized
        unsafe {
            std::env::set_var("PYTHONHOME", PYTHON_HOME);
        }
    }

    // Force unbuffered stdout so output is visible when captured by subprocess
    if std::env::var("PYTHONUNBUFFERED").is_err() {
        unsafe {
            std::env::set_var("PYTHONUNBUFFERED", "1");
        }
    }

    // Try to load cache if fingerprint matches
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Some(cache) = EnvCache::load(project_dir, &fingerprint) {
            // KEY OPTIMIZATION: Set PYTHONPATH BEFORE Python initializes
            // This allows Python to skip its expensive path scanning during init
            let pythonpath = cache.sys_path.join(":");
            unsafe {
                std::env::set_var("PYTHONPATH", &pythonpath);
            }
            return Some(cache);
        }
    }

    None
}

/// Capture current Python environment and save to cache.
fn capture_and_cache_env(py: Python<'_>, project_dir: &Path) -> Result<()> {
    let fingerprint = match EnvCache::compute_fingerprint(project_dir) {
        Some(fp) => fp,
        None => return Ok(()), // No uv.lock, nothing to cache
    };

    // Get sys.path
    let sys = py.import("sys")?;
    let sys_path = sys.getattr("path")?;
    let path_list: Vec<String> = sys_path.extract()?;

    let cache = EnvCache {
        fingerprint,
        sys_path: path_list,
        python_home: PYTHON_HOME.to_string(),
    };

    cache.save(project_dir)?;
    Ok(())
}

fn run_script(script_path: &str, cached_env: Option<EnvCache>) -> Result<()> {
    let path = Path::new(script_path);
    let code = std::fs::read_to_string(path)
        .with_context(|| format!("Failed to read script: {}", script_path))?;

    // Get the script's directory for proper imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Determine project directory (where uv.lock might be)
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    Python::with_gil(|py| {
        let sys = py.import("sys")?;
        let sys_path_obj = sys.getattr("path")?;

        // If we have cached env, inject the cached sys.path
        if let Some(ref cache) = cached_env {
            // Clear existing path and inject cached one
            sys_path_obj.call_method0("clear")?;
            for p in &cache.sys_path {
                sys_path_obj.call_method1("append", (p,))?;
            }
        }

        // Add script directory to sys.path for relative imports
        sys_path_obj.call_method1("insert", (0, &script_dir))?;

        // Set __file__ and __name__ for the script
        let globals = pyo3::types::PyDict::new(py);
        globals.set_item("__file__", script_path)?;
        globals.set_item("__name__", "__main__")?;

        // If no cache was used, capture and save for next time
        if cached_env.is_none() {
            let _ = capture_and_cache_env(py, &project_dir);
        }

        // Execute the script
        py.run(&code, Some(globals), None)
            .with_context(|| format!("Error executing script: {}", script_path))?;

        Ok(())
    })
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    // Minimal argument parsing (no clap overhead)
    if args.len() < 2 {
        print!("{}", USAGE);
        std::process::exit(0);
    }

    match args[1].as_str() {
        "-h" | "--help" => {
            print!("{}", USAGE);
            std::process::exit(0);
        }
        "-V" | "--version" => {
            println!("velo {}", env!("CARGO_PKG_VERSION"));
            std::process::exit(0);
        }
        "run" => {
            if args.len() < 3 {
                eprintln!("Error: missing script path");
                eprintln!("Usage: velo run <script.py>");
                std::process::exit(1);
            }

            // Determine project directory
            let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

            // Setup Python environment, potentially loading cache
            let cached_env = setup_python_env(&project_dir);

            run_script(&args[2], cached_env)?;
        }
        cmd => {
            eprintln!("Error: unknown command '{}'", cmd);
            eprintln!("{}", USAGE);
            std::process::exit(1);
        }
    }

    Ok(())
}
