//! `velo test` command - Thin wrapper
//!
//! Proxies to engines::vtest::cli::cmd_vtest

use anyhow::Result;

pub fn cmd_vtest(args: &[String]) -> Result<()> {
    velo_test::cli::cmd_vtest(args)
}
