use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use pyo3::prelude::*;
use std::path::Path;

/// Python home path discovered at compile time
const PYTHON_HOME: &str = env!("VELO_PYTHON_HOME");

#[derive(Parser)]
#[command(name = "velo")]
#[command(about = "The high-performance Python runtime for the AI era")]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Run a Python script
    Run {
        /// Path to the Python script
        script: String,
    },
}

/// Setup Python environment before initializing the interpreter
fn setup_python_env() {
    // Only set PYTHONHOME if not already set
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
}

fn run_script(script_path: &str) -> Result<()> {
    let path = Path::new(script_path);
    let code = std::fs::read_to_string(path)
        .with_context(|| format!("Failed to read script: {}", script_path))?;

    // Get the script's directory for proper imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    Python::with_gil(|py| {
        // Add script directory to sys.path for relative imports
        let sys = py.import("sys")?;
        let sys_path = sys.getattr("path")?;
        sys_path.call_method1("insert", (0, &script_dir))?;

        // Set __file__ and __name__ for the script
        let globals = pyo3::types::PyDict::new(py);
        globals.set_item("__file__", script_path)?;
        globals.set_item("__name__", "__main__")?;

        // Execute the script
        py.run(&code, Some(globals), None)
            .with_context(|| format!("Error executing script: {}", script_path))?;

        Ok(())
    })
}

fn main() -> Result<()> {
    // Setup Python environment before PyO3 initializes
    setup_python_env();

    let cli = Cli::parse();

    match cli.command {
        Commands::Run { script } => {
            run_script(&script)?;
        }
    }

    Ok(())
}
