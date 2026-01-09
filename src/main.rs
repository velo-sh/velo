//! Velo - The high-performance Python runtime for the AI era
//!
//! Main binary entry point. All logic is in the library crate.

use anyhow::Result;

fn main() -> Result<()> {
    // RFC-0017: Ignore SIGPIPE to prevent Rust runtime crashes when writing to broken pipes.
    // This is standard practice for CLI tools (ripgrep, fd, bat, etc.).
    // Without this, pipe saturation tests and piped output scenarios can trigger:
    // "fatal runtime error: assertion failed: output.write(&bytes).is_ok(), aborting"
    #[cfg(unix)]
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    velo::cli::run()
}
