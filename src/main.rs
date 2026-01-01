use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

mod cache;
use cache::EnvCache;

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

/// Detect the project's Python interpreter.
/// Priority:
/// 1. .venv/bin/python (uv/virtualenv)
/// 2. VELO_PYTHON environment variable
/// 3. System python3
fn detect_python(project_dir: &Path) -> Result<std::path::PathBuf> {
    // 1. Check for .venv/bin/python
    let venv_python = project_dir.join(".venv/bin/python");
    if venv_python.exists() {
        return Ok(venv_python);
    }

    // 2. Check VELO_PYTHON env var
    if let Ok(python) = std::env::var("VELO_PYTHON") {
        let path = std::path::PathBuf::from(&python);
        if path.exists() {
            return Ok(path);
        }
    }

    // 3. Fall back to system python3
    // First check if python3 exists in PATH
    if let Ok(output) = Command::new("which").arg("python3").output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            return Ok(std::path::PathBuf::from(path));
        }
    }

    anyhow::bail!("No Python interpreter found. Please create a .venv or set VELO_PYTHON")
}

/// Detect .venv/lib/python*/site-packages
fn detect_venv_site_packages(project_dir: &Path) -> Option<String> {
    let venv_lib = project_dir.join(".venv/lib");
    if !venv_lib.exists() {
        return None;
    }

    if let Ok(entries) = std::fs::read_dir(&venv_lib) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if name_str.starts_with("python3") {
                let site_packages = entry.path().join("site-packages");
                if site_packages.exists() {
                    return Some(site_packages.to_string_lossy().to_string());
                }
            }
        }
    }

    None
}

/// Capture sys.path from Python and cache it.
fn capture_sys_path(python: &Path) -> Result<Vec<String>> {
    let output = Command::new(python)
        .args(["-c", "import sys; print('\\n'.join(sys.path))"])
        .output()
        .context("Failed to run Python to capture sys.path")?;

    if !output.status.success() {
        anyhow::bail!("Python failed to report sys.path");
    }

    let paths: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(paths)
}

/// Setup Python environment, potentially using cache.
fn setup_python_env(project_dir: &Path, python: &Path) -> Option<String> {
    // Auto-detect venv site-packages
    let venv_site_packages = detect_venv_site_packages(project_dir);

    // Try to load cache if fingerprint matches
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Some(cache) = EnvCache::load(project_dir, &fingerprint) {
            let mut paths = cache.sys_path.clone();

            // Prepend venv site-packages if detected
            if let Some(ref venv_path) = venv_site_packages {
                if !paths.contains(venv_path) {
                    paths.insert(0, venv_path.clone());
                }
            }

            return Some(paths.join(":"));
        }
    }

    // No cache - capture fresh and save
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Ok(paths) = capture_sys_path(python) {
            let cache = EnvCache {
                fingerprint: fingerprint.clone(),
                sys_path: paths.clone(),
                python_home: String::new(), // Not used in subprocess mode
            };
            let _ = cache.save(project_dir);

            let mut result_paths = paths;
            if let Some(ref venv_path) = venv_site_packages {
                if !result_paths.contains(venv_path) {
                    result_paths.insert(0, venv_path.clone());
                }
            }

            return Some(result_paths.join(":"));
        }
    }

    // Fall back to just venv site-packages
    venv_site_packages
}

fn run_script(python: &Path, script_path: &str, pythonpath: Option<String>) -> Result<()> {
    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Get script directory for relative imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}", script_dir, pp),
        None => script_dir,
    };

    // Run the script using user's Python
    let status = Command::new(python)
        .env("PYTHONPATH", &final_pythonpath)
        .env("PYTHONUNBUFFERED", "1")
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

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

            // Detect user's Python
            let python = detect_python(&project_dir)?;

            // Setup environment with caching
            let pythonpath = setup_python_env(&project_dir, &python);

            // Run the script
            run_script(&python, &args[2], pythonpath)?;
        }
        cmd => {
            eprintln!("Error: unknown command '{}'", cmd);
            eprintln!("{}", USAGE);
            std::process::exit(1);
        }
    }

    Ok(())
}
