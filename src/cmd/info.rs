//! Handle 'velo info' command

use anyhow::Result;
use std::path::Path;

use crate::cache::EnvCache;
use crate::{hardware, python, python_info};

/// Handle 'velo info' command
pub fn cmd_info() -> Result<()> {
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    println!("Velo {}", env!("CARGO_PKG_VERSION"));
    println!("══════════════════════════════════════════════════════════════\n");

    // Hardware info
    let hw_info = hardware::HardwareInfo::detect();
    println!("{}\n", hw_info.format());

    // Python environment
    if let Ok(python_path) = python::detect_python(&project_dir) {
        println!("▸ Python Environment");
        println!("├─ Path:    {}", python_path.display());
        if let Ok(info) = python_info::PythonInfo::detect(&python_path) {
            println!("├─ Version: {}", info.version);
            println!("├─ ABI:     {}-{}", info.abi_tag, info.platform_tag);
        }
        println!();
    } else {
        println!("▸ Python Environment");
        println!("└─ Not detected (no .venv or VELO_PYTHON set)\n");
    }

    // Cache status
    println!("▸ Cache Status");
    let cache_dir = EnvCache::cache_dir(&project_dir);
    if cache_dir.exists() {
        if let Some(fingerprint) = EnvCache::compute_fingerprint(&project_dir) {
            if let Some(cache) = EnvCache::load(&project_dir, &fingerprint) {
                println!("├─ Location:    {}", cache_dir.display());
                println!("├─ Fingerprint: {}...", &fingerprint[..16]);
                println!(
                    "├─ Python:      {} ({})",
                    cache.python_version, cache.abi_tag
                );
                println!("├─ Version:     v{}", cache.cache_version);
                println!("└─ Status:      Valid ✅");
            } else {
                println!("├─ Location:    {}", cache_dir.display());
                println!("└─ Status:      Stale (fingerprint mismatch) ⚠️");
            }
        } else {
            println!("├─ Location:    {}", cache_dir.display());
            println!("└─ Status:      No uv.lock found");
        }
    } else {
        println!("└─ No cache (run a script first)\n");
    }

    // Custody Status (Embedded Toolchain)
    println!("▸ Custody Status");
    {
        use crate::custody::{Custodian, UvCustodian};
        let custodian = UvCustodian::new();

        // ensure() triggers extraction if missing or verification fails
        match custodian.ensure() {
            Ok(path) => {
                println!("├─ Embedded uv: Ready ✅");
                println!("├─ Location:    {}", path.display());
                println!("└─ Integrity:   BLAKE3 Verified");
            }
            Err(e) => {
                println!("├─ Embedded uv: Failed ❌");
                println!("└─ Error:       {}", e);
            }
        }
        println!();
    }

    // Zygote Status
    println!("▸ Zygote Status");
    if !crate::zygote::is_supported() {
        println!("└─ Not supported on this platform ⚠️");
    } else {
        use crate::zygote::ipc::ZygoteResponse;
        match crate::zygote::get_status() {
            Ok(ZygoteResponse::Status { pid, preload, .. }) => {
                println!("├─ PID:     {}", pid);
                if preload.is_empty() {
                    println!("└─ Preload: None");
                } else {
                    println!("└─ Preload: {}", preload.join(", "));
                }
                println!("   Status:  Active ✅");
            }
            _ => {
                println!("└─ Status:  Not running (run with --zygote)");
            }
        }
    }

    Ok(())
}
