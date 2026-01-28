//! Shadow Python command - proxy to embedded uv toolchain (RFC-0018)
//!
//! Provides `velo python` and `velo pip` commands that transparently
//! use the managed uv toolchain, ensuring hermetic environment execution.

use anyhow::Result;

use velo_core::custody::{Custodian, UvCustodian};

/// Execute `velo python <args>` - shadow command for Python
///
/// This proxies to: `uv run --no-config python <args>`
pub fn cmd_python(args: &[String]) -> Result<()> {
    let custodian = UvCustodian::new();
    let uv_path = custodian.ensure().map_err(|e| anyhow::anyhow!("{}", e))?;

    // Remove "python" from args, keep the rest
    let python_args: Vec<&str> = args.iter().skip(2).map(|s| s.as_str()).collect();

    // Build uv command: uv run --no-config python <args>
    let mut cmd_args = vec!["run", "--no-config", "python"];
    cmd_args.extend(python_args);

    let status = std::process::Command::new(&uv_path)
        .args(&cmd_args)
        // Surgical environment: scrub pollutants (RFC-0012)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env_remove("PIP_INDEX_URL")
        .env_remove("PIP_EXTRA_INDEX_URL")
        .status()
        .map_err(|e| anyhow::anyhow!("failed to execute python: {}", e))?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

/// Execute `velo pip <args>` - shadow command for pip
///
/// This proxies to: `uv pip <args>`
pub fn cmd_pip(args: &[String]) -> Result<()> {
    let custodian = UvCustodian::new();
    let uv_path = custodian.ensure().map_err(|e| anyhow::anyhow!("{}", e))?;

    // Remove "pip" from args, keep the rest
    let pip_args: Vec<&str> = args.iter().skip(2).map(|s| s.as_str()).collect();

    // Build uv command: uv pip <args>
    let mut cmd_args = vec!["pip"];
    cmd_args.extend(pip_args);

    let status = std::process::Command::new(&uv_path)
        .args(&cmd_args)
        // Surgical environment
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env_remove("PIP_INDEX_URL")
        .env_remove("PIP_EXTRA_INDEX_URL")
        .status()
        .map_err(|e| anyhow::anyhow!("failed to execute pip: {}", e))?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_custodian_can_be_created() {
        let custodian = UvCustodian::new();
        // Just verify it doesn't panic
        let _ = custodian.target_path();
    }
}
