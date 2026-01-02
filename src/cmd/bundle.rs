//! Bundle commands for Velo Fast Loader
//!
//! RFC-0006 Phase 5.0.3: Bundle CLI
//!
//! Commands:
//! - velo bundle inspect <path>
//! - velo bundle build (future)

use anyhow::{Result, anyhow};
use std::path::Path;

/// Hash algorithm identifiers (RFC-0006)
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum HashAlgorithm {
    Blake3 = 0,
    // Reserved: Sha256 = 1, Sha3 = 2
}

impl HashAlgorithm {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0 => Some(HashAlgorithm::Blake3),
            _ => None,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            HashAlgorithm::Blake3 => "BLAKE3",
        }
    }
}

/// Bundle header info (parsed from file)
#[derive(Debug)]
pub struct BundleInfo {
    pub magic: [u8; 4],
    pub version: u32,
    pub hash_algorithm: HashAlgorithm,
    pub module_count: u32,
    pub index_offset: u64,
    pub content_hash: [u8; 32],
    pub total_size: u64,
    pub modules: Vec<ModuleInfo>,
}

/// Module info from bundle index
#[derive(Debug)]
pub struct ModuleInfo {
    pub name: String,
    pub offset: u64,
    pub size: u64,
    pub hash: [u8; 32],
    pub is_package: bool,
}

/// Parse bundle header and index
pub fn read_bundle_info(path: &Path) -> Result<BundleInfo> {
    use std::io::Read;

    let mut file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;
    let total_size = metadata.len();

    // Read entire file (bundles are max 256MB)
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;

    if data.len() < 128 {
        return Err(anyhow!("Bundle too small"));
    }

    // Parse header
    let magic: [u8; 4] = data[0..4].try_into()?;
    if &magic != b"VELO" {
        return Err(anyhow!("Invalid bundle magic: {:?}", magic));
    }

    let version = u32::from_le_bytes(data[4..8].try_into()?);
    let module_count = u32::from_le_bytes(data[8..12].try_into()?);
    let index_offset = u64::from_le_bytes(data[12..20].try_into()?);

    let mut content_hash = [0u8; 32];
    content_hash.copy_from_slice(&data[20..52]);

    // Hash algorithm is at byte 52 (after content_hash)
    let hash_algo_byte = if data.len() > 52 { data[52] } else { 0 };
    let hash_algorithm = HashAlgorithm::from_u8(hash_algo_byte).unwrap_or(HashAlgorithm::Blake3);

    // Parse module index
    let mut modules = Vec::new();
    let mut pos = index_offset as usize;

    for _ in 0..module_count {
        if pos + 2 > data.len() {
            break;
        }

        // Read name length and name
        let name_len = u16::from_le_bytes(data[pos..pos + 2].try_into()?) as usize;
        pos += 2;

        if pos + name_len > data.len() {
            break;
        }
        let name = String::from_utf8_lossy(&data[pos..pos + name_len]).to_string();
        pos += name_len;

        // Read offset, size
        if pos + 16 > data.len() {
            break;
        }
        let offset = u64::from_le_bytes(data[pos..pos + 8].try_into()?);
        pos += 8;
        let size = u64::from_le_bytes(data[pos..pos + 8].try_into()?);
        pos += 8;

        // Read hash
        if pos + 32 > data.len() {
            break;
        }
        let mut hash = [0u8; 32];
        hash.copy_from_slice(&data[pos..pos + 32]);
        pos += 32;

        // Read is_package flag
        let is_package = if pos < data.len() {
            let flag = data[pos];
            pos += 1;
            flag != 0
        } else {
            false
        };

        modules.push(ModuleInfo {
            name,
            offset,
            size,
            hash,
            is_package,
        });
    }

    Ok(BundleInfo {
        magic,
        version,
        hash_algorithm,
        module_count,
        index_offset,
        content_hash,
        total_size,
        modules,
    })
}

/// Verify bundle integrity using BLAKE3
pub fn verify_bundle(path: &Path) -> Result<bool> {
    let info = read_bundle_info(path)?;

    // Read data section
    let data = std::fs::read(path)?;
    let data_section = &data[128..info.index_offset as usize];

    // Compute hash
    let computed = blake3::hash(data_section);

    Ok(computed.as_bytes() == &info.content_hash)
}

/// Format size for display
fn format_size(bytes: u64) -> String {
    if bytes >= 1024 * 1024 {
        format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0))
    } else if bytes >= 1024 {
        format!("{:.1} KB", bytes as f64 / 1024.0)
    } else {
        format!("{} bytes", bytes)
    }
}

/// Print bundle info
pub fn cmd_bundle_inspect(args: &[String]) -> Result<()> {
    if args.len() < 4 {
        eprintln!("Usage: velo bundle inspect <path> [--verify] [--modules] [--json]");
        std::process::exit(1);
    }

    let path = std::path::Path::new(&args[3]);
    let verify = args.iter().any(|a| a == "--verify");
    let show_modules = args.iter().any(|a| a == "--modules");
    let json_output = args.iter().any(|a| a == "--json");

    if !path.exists() {
        return Err(anyhow!("Bundle not found: {}", path.display()));
    }

    let info = read_bundle_info(path)?;

    if json_output {
        // JSON output for tooling
        let mut modules_json = Vec::new();
        for m in &info.modules {
            modules_json.push(format!(
                r#"{{"name":"{}","size":{},"is_package":{}}}"#,
                m.name, m.size, m.is_package
            ));
        }

        println!(
            r#"{{
  "magic": "VELO",
  "version": {},
  "hash_algorithm": "{}",
  "module_count": {},
  "total_size": {},
  "content_hash": "{}",
  "modules": [{}]
}}"#,
            info.version,
            info.hash_algorithm.name(),
            info.module_count,
            info.total_size,
            hex::encode(&info.content_hash[..16]),
            modules_json.join(",")
        );
    } else {
        // Human-readable output
        println!();
        println!("Bundle: {}", path.display());
        println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
        println!("  Magic:          {}", String::from_utf8_lossy(&info.magic));
        println!("  Version:        {}", info.version);
        println!("  Hash Algorithm: {}", info.hash_algorithm.name());
        println!("  Modules:        {}", info.module_count);
        println!("  Size:           {}", format_size(info.total_size));
        println!(
            "  Content Hash:   {}...",
            hex::encode(&info.content_hash[..16])
        );

        if verify {
            let valid = verify_bundle(path)?;
            if valid {
                println!("  Integrity:      ✓ Verified");
            } else {
                println!("  Integrity:      ✗ FAILED");
            }
        }

        if show_modules {
            println!();
            println!("Modules:");

            // Sort by size descending
            let mut sorted: Vec<_> = info.modules.iter().collect();
            sorted.sort_by(|a, b| b.size.cmp(&a.size));

            for (i, m) in sorted.iter().take(20).enumerate() {
                let pkg = if m.is_package { " [pkg]" } else { "" };
                println!("  {:2}. {} ({}){}", i + 1, m.name, format_size(m.size), pkg);
            }

            if sorted.len() > 20 {
                println!("  ... and {} more", sorted.len() - 20);
            }
        } else {
            // Show top 3 by default
            println!();
            println!("Top modules by size:");

            let mut sorted: Vec<_> = info.modules.iter().collect();
            sorted.sort_by(|a, b| b.size.cmp(&a.size));

            for (i, m) in sorted.iter().take(3).enumerate() {
                println!("  {}. {} ({})", i + 1, m.name, format_size(m.size));
            }
        }
    }

    Ok(())
}

/// Main bundle command dispatcher
pub fn cmd_bundle(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Usage: velo bundle <inspect|build> [options]");
        eprintln!();
        eprintln!("Subcommands:");
        eprintln!("  inspect <path>  Show bundle information");
        eprintln!("  build           Build bundle from project (not yet implemented)");
        std::process::exit(1);
    }

    match args[2].as_str() {
        "inspect" => cmd_bundle_inspect(args),
        "build" => {
            eprintln!("velo bundle build: Use Python builder for now");
            eprintln!("  python python/bundle_builder.py <project_dir>");
            std::process::exit(1);
        }
        subcmd => {
            eprintln!("Unknown bundle subcommand: {}", subcmd);
            std::process::exit(1);
        }
    }
}
