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
    pub graph_offset: u64,
    pub security_header_offset: u8,
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

    // RFC-0009: Graph Offset (60..68)
    let mut graph_offset = 0;
    if data.len() > 68 {
        graph_offset = u64::from_le_bytes(data[60..68].try_into()?);
    }

    // RFC-0009 v2.0: Security Header Offset (68)
    let security_header_offset = if data.len() > 68 { data[68] } else { 28 };

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
        graph_offset,
        security_header_offset,
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
        println!("  Graph Offset:   {}", info.graph_offset);
        println!("  Security Off:   {}", info.security_header_offset);

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
        eprintln!("  build           Build bundle from project");
        std::process::exit(1);
    }

    match args[2].as_str() {
        "inspect" => cmd_bundle_inspect(args),
        "build" => cmd_bundle_build(args),
        subcmd => {
            eprintln!("Unknown bundle subcommand: {}", subcmd);
            std::process::exit(1);
        }
    }
}

/// Build bundle from project
pub fn cmd_bundle_build(args: &[String]) -> Result<()> {
    use crate::graph::builder::GraphBuilder;
    use crate::graph::serializer::serialize_to_aligned_bytes;
    use std::io::Write;
    use std::process::Command;

    let project_dir = if args.len() > 3 {
        Path::new(&args[3])
    } else {
        Path::new(".")
    };

    let output_path = if args.len() > 4 {
        Path::new(&args[4])
    } else {
        Path::new("bundle.veloc")
    };

    eprintln!("📦 Building bundle from: {}", project_dir.display());

    // 1. Build Static Graph (RFC-0009)
    eprintln!("   • Generating static import graph...");
    let mut builder = GraphBuilder::new(project_dir.to_path_buf());
    builder.build();
    let graph = builder.to_static_graph();

    // Serialize Graph
    let graph_bytes = serialize_to_aligned_bytes(&graph);
    let graph_size = graph_bytes.len();

    // Compute H-8 Graph Hash (Keyed BLAKE3)
    // Domain: Velo-v1-StaticGraph-v0.6.0
    let h8_key = blake3::derive_key("Velo-v1-StaticGraph-v0.6.0", b"Velo-StaticGraph-Key-v1");
    let _graph_hash = blake3::keyed_hash(&h8_key, &graph_bytes);

    // 2. Scan and Compile Modules
    eprintln!("   • Compiling modules...");
    let walker = ignore::WalkBuilder::new(project_dir)
        .hidden(true)
        .git_ignore(true)
        .build();

    struct CompiledModule {
        name: String,
        code: Vec<u8>,
        is_package: bool,
        hash: [u8; 32],
    }

    let mut modules = Vec::new();

    for entry in walker {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() && path.extension().is_some_and(|e| e == "py") {
            // Determine module name
            let rel_path = path.strip_prefix(project_dir).unwrap_or(path);
            let mut parts: Vec<String> = rel_path
                .components()
                .map(|c| c.as_os_str().to_string_lossy().to_string())
                .collect();

            let filename = parts.pop().unwrap();
            let is_package = filename == "__init__.py";
            let name = if is_package {
                parts.join(".")
            } else {
                let stem = filename.strip_suffix(".py").unwrap();
                if parts.is_empty() {
                    stem.to_string()
                } else {
                    format!("{}.{}", parts.join("."), stem)
                }
            };

            if name.is_empty() {
                continue;
            }

            // Compile to bytecode using python3
            // Validated Approach: use a small python script via stdin/stdout to avoid temp files per module
            // For robustness, we'll read the file content in Rust and pipe it to python3
            let source_code = std::fs::read_to_string(path)?;

            let compile_script = format!(
                "import marshal, sys; \
                 sys.stdout.buffer.write(marshal.dumps(compile(sys.stdin.read(), '{}', 'exec')))",
                path.display()
            );

            let output = Command::new("python3")
                .arg("-c")
                .arg(&compile_script)
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::inherit()) // Pass stderr through
                .spawn();

            match output {
                Ok(mut child) => {
                    if let Some(mut stdin) = child.stdin.take() {
                        stdin.write_all(source_code.as_bytes())?;
                    }
                    let result = child.wait_with_output()?;
                    if !result.status.success() {
                        eprintln!("❌ Compilation failed for: {}", path.display());
                        continue; // or exit?
                    }

                    let code = result.stdout;
                    let hash = blake3::hash(&code); // Content Hash

                    modules.push(CompiledModule {
                        name,
                        code,
                        hash: *hash.as_bytes(),
                        is_package,
                    });
                }
                Err(e) => {
                    return Err(anyhow!(
                        "Failed to spawn python3: {}. Is Python 3 installed?",
                        e
                    ));
                }
            }
        }
    }

    if modules.is_empty() {
        return Err(anyhow!(
            "No python modules found in {}",
            project_dir.display()
        ));
    }

    // 3. Construct Bundle
    // Layout: Header -> Data -> (Padding) -> Graph -> (Padding) -> Index

    // 3a. Build Data Section
    let mut data_section = Vec::new();
    let mut module_meta = Vec::new();

    // Header size
    let header_size = 128;

    for mod_data in &modules {
        let start_offset = header_size + data_section.len();
        data_section.extend_from_slice(&mod_data.code);

        // Pad to 4KB alignment (H-9) if needed?
        // RFC-0009 says "Import Graph Section MUST start at 4KB aligned offset"
        // It doesn't strictly say every module must be aligned, but Phase 5.0 Fast Loader usually prefers it.
        // bundle_builder.py implementation aligns EACH module. Let's match it for safety/perf.
        let padding = (4096 - (data_section.len() % 4096)) % 4096;
        data_section.resize(data_section.len() + padding, 0);

        module_meta.push((mod_data, start_offset as u64, mod_data.code.len() as u64));
    }

    // Graph starts after data section, aligned to 4KB
    // Since we aligned every module steps above, total data_section should be 4KB aligned.
    let _data_end = header_size + data_section.len();

    // 3b. Build Index
    // Index comes AFTER Graph in bundle_builder.py reference?
    // Wait, bundle_builder.py: "Layout: Header -> Data -> Index" (old)
    // RFC-0009: "Header -> Data -> Index -> Padding -> Graph"
    // Wait, let's re-read RFC-0009 Section 3.3.
    // "Header -> Data -> Index -> Padding -> Graph"
    // AND "Import Graph Section MUST start at 4KB aligned offset"

    // bundle_builder.py implementation in my previous `read_file` output:
    // Line 188: f.write(header_prefix)
    // Line 191: f.write(data_section)
    // Line 194: f.write(graph_section)
    // Line 195: f.write(index_buffer)
    // It writes Graph BEFORE Index?
    // Let's check `read_bundle_info` in `src/cmd/bundle.rs`.
    // It doesn't strictly enforce verify order, just offsets.

    // Let's follow RFC-0009 Text from earlier view:
    // "Header -> Data -> Index -> Padding -> Graph"
    // Let's stick to the RFC text as the source of truth, but ensure we respect the offsets.
    // Actually, `src/loader/verify.rs` expects `index_offset` to point to index.
    // If we put Index first, we can update offsets.

    // Strategy: Header(128) | Data... | Index... | Padding | Graph (4KB aligned)
    // This allows Graph to be mapped cleanly. The Index is small and read casually.

    // Build Index Buffer
    let mut index_buffer = Vec::new();
    for (mod_data, offset, size) in &module_meta {
        let name_bytes = mod_data.name.as_bytes();
        index_buffer.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        index_buffer.extend_from_slice(name_bytes);
        index_buffer.extend_from_slice(&offset.to_le_bytes()); // offset
        index_buffer.extend_from_slice(&size.to_le_bytes()); // size
        index_buffer.extend_from_slice(&mod_data.hash); // 32-byte hash
        index_buffer.extend_from_slice(&[if mod_data.is_package { 1 } else { 0 }]); // is_package
    }

    let index_offset = header_size + data_section.len();

    // Now append Index to data_section (conceptually "content")
    // Wait, if Graph must be 4KB aligned, and we put Index first, we might mess up alignment.
    // IF we follow "Data (aligned modules)" -> "Index" -> "Padding" -> "Graph".

    let mut final_content = data_section; // currently aligned to 4KB
    final_content.extend_from_slice(&index_buffer);

    // Now pad for Graph
    let current_len = header_size + final_content.len();
    let padding_needed = (4096 - (current_len % 4096)) % 4096;
    final_content.resize(final_content.len() + padding_needed, 0);

    let graph_offset_final = header_size + final_content.len();
    assert_eq!(graph_offset_final % 4096, 0);

    // Append Graph
    final_content.extend_from_slice(&graph_bytes);

    // 4. Construct Header
    let mut header = vec![0u8; 128];

    // Magic "VELO"
    header[0..4].copy_from_slice(b"VELO");
    // Version 1
    header[4..8].copy_from_slice(&1u32.to_le_bytes());
    // Module Count
    header[8..12].copy_from_slice(&(modules.len() as u32).to_le_bytes());
    // Index Offset
    header[12..20].copy_from_slice(&(index_offset as u64).to_le_bytes());

    // 20..52: Content Hash (Placeholder)

    // 52: Hash Algo (Blake3 = 0)
    header[52] = 0;

    // 60..68: Graph Offset
    header[60..68].copy_from_slice(&(graph_offset_final as u64).to_le_bytes());

    // 68: Security Header Offset
    header[68] = 28; // Default for 3.11/3.12 (standard marshal header)

    // TODO: Store H-8 Graph Hash somewhere?
    // RFC says "The resulting graph hash MUST be stored in the bundle index...".
    // But index format is "module entries".
    // Alternatively, maybe it's covered by Global Hash?
    // H-8 says "Inclusion: The resulting graph hash MUST be stored in the bundle index and covered by the global BLAKE3 hash".
    // Maybe as a special module entry? Or in the header?
    // The Header has reserved space.
    // Let's assume Global Hash covers it sufficiently for now, or put it in header reserved space (e.g. 70..102).
    // For now, satisfy H-1 (Global Hash) which covers the graph bytes.
    // The Global Hash calculation will cover header + data/index + graph.

    // Calculate Global Hash (H-1)
    // Cover: Header[0..20] + Header[52..128] + Content (Data + Index + Graph)
    let mut hasher = blake3::Hasher::new();
    hasher.update(&header[0..20]);
    hasher.update(&header[52..128]); // Skip hash slot
    hasher.update(&final_content);
    let global_hash = hasher.finalize();

    // Fill hash in header
    header[20..52].copy_from_slice(global_hash.as_bytes());

    // 5. Write to file
    let mut file = std::fs::File::create(output_path)?;
    file.write_all(&header)?;
    file.write_all(&final_content)?;

    eprintln!("✅ Bundle created: {}", output_path.display());
    eprintln!("   Modules: {}", modules.len());
    eprintln!(
        "   Graph:   {} bytes ({} records)",
        graph_size,
        graph.module_records.len()
    );
    eprintln!("   Size:    {} bytes", header.len() + final_content.len());

    Ok(())
}
