//! Vibe command handler (RFC-0029)

use anyhow::Result;
use colored::Colorize;

use crate::engines::v_live::engine::VibeEngine;
use std::path::PathBuf;

/// Handler for `velo vibe` and `velo live`
#[tokio::main]
pub async fn cmd_vibe(args: &[String]) -> Result<()> {
    // Determine port: CLI arg > Env Var > Default
    let mut port = "8080".to_string();
    if let Ok(env_port) = std::env::var("VELO_VIBE_PORT")
        && !env_port.is_empty()
    {
        port = env_port;
    }

    // Crude CLI parsing for Phase 8
    for i in 0..args.len() {
        if args[i] == "--port" && i + 1 < args.len() {
            port = args[i + 1].clone();
        }
    }

    let gateway_addr = format!("127.0.0.1:{}", port);

    // Help handling
    if args.iter().any(|arg| arg == "--help" || arg == "-h") || args.len() < 3 {
        println!("{}", "🏛️  Vibe Engine Activated".green().bold());
        println!("Architecture Directive: Phase 8 (Vibe-Coding)");
        println!("\nUsage: velo vibe <target> [OPTIONS]");
        println!("\nOPTIONS:");
        println!("    --port <PORT>    Vibe gateway port (default: 8080 or VELO_VIBE_PORT)");
        return Ok(());
    }

    let target = PathBuf::from(&args[2]);

    println!("{}", "🏛️  Vibe Engine Activated".green().bold());
    println!("Architecture Directive: Phase 8 (Vibe-Coding)");

    let engine = VibeEngine::new(target, &gateway_addr);
    engine.start().await?;

    Ok(())
}
