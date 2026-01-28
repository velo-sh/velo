//! Graph management commands for Velo Static Graph
//!
//! RFC-0009 Phase 6.0: Graph CLI
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::{Path, PathBuf};

use velo_core::graph::builder::GraphBuilder;
use velo_core::graph::serializer;

/// Static import graph management
#[derive(Parser, Debug)]
#[command(name = "graph", about = "Static import graph management")]
pub struct GraphCmd {
    #[command(subcommand)]
    pub command: GraphSubcommand,
}

#[derive(Subcommand, Debug)]
pub enum GraphSubcommand {
    /// Generate static import graph from project
    Generate {
        /// Project directory to scan
        #[arg(required = true)]
        project_dir: PathBuf,

        /// Output file path for the graph
        #[arg(long, required = true)]
        output: PathBuf,
    },
}

/// Handle 'velo graph' command (entry point from cli.rs)
pub fn cmd_graph(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = GraphCmd::try_parse_from(&args[1..])?;

    match cmd.command {
        GraphSubcommand::Generate {
            project_dir,
            output,
        } => cmd_graph_generate(&project_dir, &output),
    }
}

fn cmd_graph_generate(project_dir: &Path, output_path: &Path) -> Result<()> {
    eprintln!("🔍 Scanning project: {}", project_dir.display());
    let mut builder = GraphBuilder::new(project_dir.to_path_buf());
    builder.build();

    let static_graph = builder.to_static_graph();
    let bytes = serializer::serialize_to_aligned_bytes(&static_graph);

    std::fs::write(output_path, &bytes)?;
    eprintln!(
        "✅ Graph generated: {} ({} bytes)",
        output_path.display(),
        bytes.len()
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_generate_subcommand() {
        let cmd = GraphCmd::try_parse_from([
            "graph",
            "generate",
            "/path/to/project",
            "--output",
            "graph.bin",
        ])
        .unwrap();

        match cmd.command {
            GraphSubcommand::Generate {
                project_dir,
                output,
            } => {
                assert_eq!(project_dir.to_str().unwrap(), "/path/to/project");
                assert_eq!(output.to_str().unwrap(), "graph.bin");
            }
        }
    }

    #[test]
    fn test_missing_output_error() {
        let result = GraphCmd::try_parse_from(["graph", "generate", "/path/to/project"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_missing_project_dir_error() {
        let result = GraphCmd::try_parse_from(["graph", "generate", "--output", "graph.bin"]);
        assert!(result.is_err());
    }
}
