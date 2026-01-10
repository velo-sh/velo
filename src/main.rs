//! Velo - The high-performance Python runtime for the AI era
//!
//! Main binary entry point. All logic is in the library crate.

use anyhow::Result;

fn main() -> Result<()> {
    // RFC-0017: Ignore SIGPIPE to prevent Rust runtime crashes when writing to broken pipes.
    // This is standard practice for CLI tools (ripgrep, fd, bat, etc.).
    #[cfg(unix)]
    // SECURITY: Ignoring SIGPIPE is a standard stability practice for CLI tools
    // to prevent unconditional aborts when a pipe consumer (like 'head' or 'less') closes early.
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    velo::cli::run()
}
