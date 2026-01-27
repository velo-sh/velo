//! Handle 'velo serve' command - Thin wrapper
//!
//! Proxies to engines::serve::cli::cmd_serve

use anyhow::Result;

pub fn cmd_serve(args: &[String]) -> Result<()> {
    velo_serve::cli::cmd_serve(args)
}
