//! Graph management commands for Velo Static Graph
//!
//! RFC-0009 Phase 6.0: Graph CLI
//!
//! Commands:
//! - velo graph generate <project_dir> --output <path>

use crate::graph::builder::GraphBuilder;
use crate::graph::serializer;
use anyhow::{Context, Result};
use std::path::{Path, PathBuf};

pub fn cmd_graph(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        print_usage();
        std::process::exit(1);
    }

    match args[2].as_str() {
        "generate" => cmd_graph_generate(args),
        _ => {
            print_usage();
            std::process::exit(1);
        }
    }
}

fn print_usage() {
    eprintln!("Usage: velo graph <generate> [options]");
    eprintln!();
    eprintln!("Subcommands:");
    eprintln!("  generate <project_dir> --output <path>  Generate static import graph");
}

fn cmd_graph_generate(args: &[String]) -> Result<()> {
    if args.len() < 5 {
        print_usage();
        std::process::exit(1);
    }

    let project_dir = Path::new(&args[3]);
    let mut output_path = None;

    for i in 4..args.len() {
        if args[i] == "--output" && i + 1 < args.len() {
            output_path = Some(PathBuf::from(&args[i + 1]));
        }
    }

    let output_path = output_path.context("Error: --output <path> is required")?;

    eprintln!("🔍 Scanning project: {}", project_dir.display());
    let mut builder = GraphBuilder::new(project_dir.to_path_buf());
    builder.build();

    let static_graph = builder.to_static_graph();
    let bytes = serializer::serialize_to_aligned_bytes(&static_graph);

    std::fs::write(&output_path, &bytes)?;
    eprintln!(
        "✅ Graph generated: {} ({} bytes)",
        output_path.display(),
        bytes.len()
    );

    Ok(())
}
