//! Velo - The high-performance Python runtime for the AI era
//!
//! Main binary entry point. All logic is in the library crate.

use anyhow::Result;

fn main() -> Result<()> {
    velo::cli::run()
}
