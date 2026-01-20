//! Vibe command handler (RFC-0029)

use anyhow::Result;
use colored::Colorize;

use crate::v_live::engine::VibeEngine;
use std::path::PathBuf;

/// Handler for `velo vibe` and `velo live`
#[tokio::main]
pub async fn cmd_vibe(args: &[String]) -> Result<()> {
    println!("{}", "🏛️  Vibe Engine Activated".green().bold());
    println!("Architecture Directive: Phase 8 (Vibe-Coding)");

    if args.len() < 3 {
        println!("\nUsage: velo vibe <target>");
        return Ok(());
    }

    let target = PathBuf::from(&args[2]);
    let gateway_addr = "127.0.0.1:8080"; // Default Vibe port

    let engine = VibeEngine::new(target, gateway_addr);
    engine.start().await?;

    Ok(())
}
