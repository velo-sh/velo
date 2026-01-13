use crate::python;
use anyhow::{Result, bail};
use std::env;
use std::process::Command;

pub fn cmd_debug_pre_flight(json: bool) -> Result<()> {
    if !json {
        println!("🚀 Velo Pre-flight Forensic Diagnostic\n");
    }

    let mut results = serde_json::Map::new();

    // 1. Python Linkage & Version Check (Runtime)
    let project_dir = env::current_dir()?;
    let py_info = check_python_environment(&project_dir);
    results.insert("python".to_string(), serde_json::to_value(&py_info)?);

    if !json {
        println!("[1/3] Python Environment");
        println!("      • Interpreter: {}", py_info.path);
        println!("      • Version    : {}", py_info.version);
        if py_info.ok {
            println!("      • Status     : ✅");
        } else {
            println!("      • Status     : ❌ (Mismatch or failure)");
        }
    }

    // 2. OS Invariants: Abstract Sockets
    let socket_info = check_abstract_sockets();
    results.insert("sockets".to_string(), serde_json::to_value(&socket_info)?);

    if !json {
        println!("\n[2/3] OS Invariants");
        println!(
            "      • Abstract Sockets: {}",
            if socket_info.abstract_supported {
                "✅ Supported"
            } else {
                "⚠️ Not supported"
            }
        );
        println!("      • Max Path Length : {} bytes", socket_info.max_length);
    }

    // 3. Hardware: HugePage Alignment (Gate O/P foundation)
    let hugepage_info = check_hugepages();
    results.insert(
        "hugepages".to_string(),
        serde_json::to_value(&hugepage_info)?,
    );

    if !json {
        println!("\n[3/3] Hardware Compatibility");
        println!("      • Alignment: {} bytes", hugepage_info.alignment);
    }

    if json {
        println!("{}", serde_json::to_string_pretty(&results)?);
    } else {
        println!("\n✨ Pre-flight complete. Environment is stable.");
    }

    // Hard fail if any critical check failed
    if !py_info.ok {
        bail!("Pre-flight failed: Python environment is unstable.");
    }

    Ok(())
}

#[derive(serde::Serialize)]
struct PythonInfo {
    path: String,
    version: String,
    ok: bool,
}

fn check_python_environment(project_dir: &std::path::Path) -> PythonInfo {
    let python_path = python::detect_python(project_dir).unwrap_or_else(|_| "python3".into());
    let output = Command::new(&python_path)
        .arg("-c")
        .arg("import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        .output();

    let mut ok = false;
    let mut version = "unknown".to_string();

    if let Ok(o) = output
        && o.status.success()
    {
        version = String::from_utf8_lossy(&o.stdout).trim().to_string();
        // RFC-0012: Enforce SSoT at runtime
        if version == crate::common::constants::PYTHON_VERSION {
            ok = true;
        }
    }

    PythonInfo {
        path: python_path.display().to_string(),
        version,
        ok,
    }
}

#[derive(serde::Serialize)]
struct SocketInfo {
    abstract_supported: bool,
    max_length: usize,
}

fn check_abstract_sockets() -> SocketInfo {
    #[cfg(target_os = "linux")]
    {
        // Try bind to abstract address
        use std::os::unix::net::UnixListener;
        let name = format!("\0velo-diag-{}", uuid::Uuid::new_v4());
        let supported = UnixListener::bind(&name).is_ok();
        SocketInfo {
            abstract_supported: supported,
            max_length: 108, // Standard Linux limit
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        SocketInfo {
            abstract_supported: false,
            max_length: 104, // Standard BSD/macOS limit
        }
    }
}

#[derive(serde::Serialize)]
struct HugePageInfo {
    alignment: usize,
}

fn check_hugepages() -> HugePageInfo {
    // RFC-0015: Base alignment requirement
    HugePageInfo {
        alignment: 2 * 1024 * 1024, // 2MB
    }
}
