use anyhow::Result;
use colored::Colorize;
use std::env;
use velo_core::common::constants;

/// Execute the 'audit' command
pub fn cmd_audit(_args: &[String]) -> Result<()> {
    println!(
        "\n{}",
        "🛡️  Velo Architectural Governance Audit".bold().cyan()
    );
    println!("{}\n", "=".repeat(40).cyan());

    let mut failures = 0;

    // 1. SPEC-0005: SSOT Consistency
    failures += audit_ssot()?;

    // 2. SPEC-0006: Sovereignty Naming
    failures += audit_sovereignty()?;

    // 3. SPEC-0007: Performance Invariants
    failures += audit_performance()?;

    // 4. SPEC-0008: Tiered Testing
    failures += audit_testing()?;

    println!("\n{}", "=".repeat(40).cyan());
    if failures == 0 {
        println!(
            "{} Architecture is in compliance.",
            "✅ PASS:".green().bold()
        );
        Ok(())
    } else {
        println!(
            "{} Found {} architectural violations.",
            "❌ FAIL:".red().bold(),
            failures
        );
        anyhow::bail!("Architectural audit failed with {} violations.", failures)
    }
}

fn audit_ssot() -> Result<usize> {
    println!("{}", "1. [SPEC-0005] SSOT Consistency Check".bold());
    let mut violations = 0;

    // Check Python version
    let expected_py = constants::PYTHON_VERSION;
    #[cfg(unix)]
    let python_path = env::var("PYO3_PYTHON").unwrap_or_else(|_| "python3".to_string());
    #[cfg(not(unix))]
    let python_path = "python";

    let py_version_out = std::process::Command::new(&python_path)
        .arg("-c")
        .arg("import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        .output();

    match py_version_out {
        Ok(output) if output.status.success() => {
            let actual = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if actual == expected_py {
                println!("  • Python version: {} (OK)", actual.green());
            } else {
                println!(
                    "  • {} Version mismatch: expected {}, got {} (FAIL)",
                    "Violation:".red(),
                    expected_py.yellow(),
                    actual.red()
                );
                violations += 1;
            }
        }
        _ => {
            println!(
                "  • {} Could not verify Python version at {}",
                "Violation:".red(),
                python_path
            );
            violations += 1;
        }
    }

    // Check for VELO_SYS_ overrides
    let mut sys_overrides = Vec::new();
    for (key, _) in env::vars() {
        if key.starts_with("VELO_SYS_") {
            sys_overrides.push(key);
        }
    }
    if sys_overrides.is_empty() {
        println!("  • Environment Hierarchy: No illegal VELO_SYS_ overrides (OK)");
    } else {
        println!(
            "  • {} Illegal VELO_SYS_ overrides detected: {:?} (FAIL)",
            "Violation:".red(),
            sys_overrides
        );
        violations += 1;
    }

    Ok(violations)
}

fn audit_sovereignty() -> Result<usize> {
    println!("\n{}", "2. [SPEC-0006] Sovereignty Naming Check".bold());
    let mut violations = 0;

    // Check a few critical files for prefixes
    let requirements = [
        ("src/zygote/core_ipc.rs", "Zygote Core"),
        ("src/common/util_log_sanitize.rs", "Common Utils"),
        ("src/shm/util_alignment.rs", "SHM Alignment"),
        ("velo_zygote/v_rsgi.py", "Python RSGI"),
        ("velo_zygote/v_shield.py", "Python Shield"),
        ("velo_zygote/v_fork.py", "Python Fork"),
    ];

    for (path, domain) in requirements {
        if std::path::Path::new(path).exists() {
            println!("  • {}: {} (OK)", domain, path.green());
        } else {
            // Check if the old name still exists (Nominal Sovereignty check)
            let old_path = if path.ends_with(".rs") {
                path.replace("core_", "").replace("util_", "")
            } else {
                path.replace("v_", "")
            };

            if std::path::Path::new(&old_path).exists() {
                println!(
                    "  • {} {} is using legacy name {} (FAIL)",
                    "Violation:".red(),
                    domain,
                    old_path.red()
                );
                violations += 1;
            } else {
                println!(
                    "  • {} {} component not found at expected path {}",
                    "Warning:".yellow(),
                    domain,
                    path.yellow()
                );
            }
        }
    }

    Ok(violations)
}

fn audit_performance() -> Result<usize> {
    println!("\n{}", "3. [SPEC-0007] Performance Invariants Check".bold());
    let violations = 0;

    // Check memfd support (Linux only hint)
    #[cfg(target_os = "linux")]
    {
        println!("  • Platform: Linux (OK)");
        // Simple check for syscall availability could go here
    }

    #[cfg(target_os = "macos")]
    {
        println!("  • Platform: macOS (Note: SHM limited, use UDS native)");
    }

    println!(
        "  • IPC Buffer: {} bytes (MAX_MESSAGE_SIZE alignment)",
        constants::MAX_MESSAGE_SIZE
    );

    Ok(violations)
}

fn audit_testing() -> Result<usize> {
    println!("\n{}", "4. [SPEC-0008] Tiered Testing Check".bold());
    let mut violations = 0;

    if std::path::Path::new("pyproject.toml").exists() {
        let content = std::fs::read_to_string("pyproject.toml")?;
        if content.contains("tier0") && content.contains("tier1") && content.contains("tier2") {
            println!("  • pyproject.toml: Tier markers present (OK)");
        } else {
            println!(
                "  • {} Tier markers missing from pyproject.toml (FAIL)",
                "Violation:".red()
            );
            violations += 1;
        }
    }

    Ok(violations)
}
