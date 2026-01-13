use std::process::Command;
use velo::common::constants;

#[test]
fn test_rust_python_parity_audit() {
    let project_dir = std::env::current_dir().unwrap();

    // We run a small python script to extract constants from the generated file
    // This avoids needing pyo3 dependency in testing while being very robust
    let py_snippet = r#"
import os
import sys

# Add project root to sys.path to allow importing velo_zygote
sys.path.insert(0, os.getcwd())

try:
    from velo_zygote import constants as c
    print(f"PROTOCOL_VERSION={c.PROTOCOL_VERSION}")
    print(f"SOCKET_PATH_LIMIT={c.SOCKET_PATH_LIMIT}")
    print(f"PYTHON_VERSION={c.PYTHON_VERSION}")
    print(f"DEFAULT_PORT={c.DEFAULT_PORT}")
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
"#;

    let output = Command::new("python3")
        .arg("-c")
        .arg(py_snippet)
        .current_dir(&project_dir)
        .output()
        .expect("Failed to execute python parity audit");

    if !output.status.success() {
        panic!(
            "Python parity audit failed to execute:\n{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut py_values = std::collections::HashMap::new();

    for line in stdout.lines() {
        if let Some((key, val)) = line.split_once('=') {
            py_values.insert(key.trim().to_string(), val.trim().to_string());
        }
    }

    // Audit 1: Protocol Version
    assert_eq!(
        py_values
            .get("PROTOCOL_VERSION")
            .expect("Missing PROTOCOL_VERSION in python"),
        &constants::PROTOCOL_VERSION.to_string(),
        "SSOT DRIFT: Rust PROTOCOL_VERSION doesn't match Python!"
    );

    // Audit 2: Socket Path Limit
    assert_eq!(
        py_values
            .get("SOCKET_PATH_LIMIT")
            .expect("Missing SOCKET_PATH_LIMIT in python"),
        &constants::SOCKET_PATH_LIMIT.to_string(),
        "SSOT DRIFT: Rust SOCKET_PATH_LIMIT doesn't match Python!"
    );

    // Audit 3: Python Version
    assert_eq!(
        py_values
            .get("PYTHON_VERSION")
            .expect("Missing PYTHON_VERSION in python"),
        constants::PYTHON_VERSION,
        "SSOT DRIFT: Rust PYTHON_VERSION doesn't match Python!"
    );

    // Audit 4: Default Port
    assert_eq!(
        py_values
            .get("DEFAULT_PORT")
            .expect("Missing DEFAULT_PORT in python"),
        &constants::DEFAULT_PORT.to_string(),
        "SSOT DRIFT: Rust DEFAULT_PORT doesn't match Python!"
    );

    println!("\n✅ SSoT Parity Verified: Rust and Python constants are in sync.");
}
