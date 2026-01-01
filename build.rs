use std::process::Command;

fn main() {
    // Discover Python home at build time and embed it
    // Use python3.11 explicitly to match the version PyO3 was compiled against
    let output = Command::new("python3.11")
        .args(["-c", "import sys; print(sys.base_prefix)"])
        .output()
        .expect("Failed to execute python3.11 to discover PYTHONHOME at build time. Ensure python3.11 is installed.");

    if !output.status.success() {
        panic!(
            "python3 discovery failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let python_home = String::from_utf8_lossy(&output.stdout).trim().to_string();
    println!("cargo:rustc-env=VELO_PYTHON_HOME={}", python_home);
    println!("cargo:rerun-if-env-changed=PYO3_PYTHON");
}
