//! Velo - The high-performance Python runtime for the AI era
//!
//! Main binary entry point. All logic is in the library crate.

use anyhow::Result;

fn main() -> Result<()> {
    // RFC-0020: Initialize global structured logging
    // Respects RUST_LOG env var for filtering, e.g. RUST_LOG=velo=debug
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn"))
        .format_timestamp_millis()
        .format_module_path(false)
        .init();

    // 🚨 SENTINEL: Cross-platform Binary Guard
    velo_core::common::check_platform_integrity();

    // RFC-0017: Ignore SIGPIPE to prevent Rust runtime crashes when writing to broken pipes.
    // This is standard practice for CLI tools (ripgrep, fd, bat, etc.).
    #[cfg(unix)]
    // SECURITY: Ignoring SIGPIPE is a standard stability practice for CLI tools
    // to prevent unconditional aborts when a pipe consumer (like 'head' or 'less') closes early.
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    // Test-mode SIGTERM fast-exit to avoid hanging processes in CI.
    #[cfg(unix)]
    if std::env::var("VELO_TEST_MODE").ok().as_deref() == Some("1") {
        // Use raw libc to avoid signal-hook dependency just for this
        unsafe {
            libc::signal(libc::SIGTERM, libc::SIG_DFL);
        }
    }

    velo::run()
}
