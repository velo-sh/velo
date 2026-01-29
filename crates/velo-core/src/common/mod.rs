pub mod diagnostics;
pub mod env_governance;
pub mod governance;
pub mod memory;
pub mod paths;
pub mod python_env;
pub mod snippet_extractor;
pub mod util_log_sanitize;

// Import generated constants from OUT_DIR
pub mod constants {
    include!(concat!(env!("OUT_DIR"), "/constants.rs"));
}

/// Check if the binary is running on the platform it was compiled for.
/// This prevents "Mach-O on Linux" errors (platform contamination).
pub fn check_platform_integrity() {
    let current_os = std::env::consts::OS;
    let current_arch = std::env::consts::ARCH;

    // We check against the COMPILED-IN constants from build.rs
    // Note: constants::BUILD_TARGET is the full triple (e.g. x86_64-apple-darwin)
    // but BUILD_TARGET_ARCH is just the arch (e.g. x86_64 or aarch64).
    let target = constants::BUILD_TARGET;
    let target_arch = constants::BUILD_TARGET_ARCH;

    let os_match = match current_os {
        "macos" => target.contains("apple-darwin"),
        "linux" => target.contains("unknown-linux-gnu") || target.contains("alpine-linux-musl"),
        _ => true, // Fallback for other platforms
    };

    let arch_match = current_arch == target_arch;

    if !os_match || !arch_match {
        eprintln!(
            "\n\n🚨 [SENTINEL FATAL] Binary Platform Mismatch!\n\
               Compiled for: {} ({})\n\
               Running on : {} ({})\n\n\
               Velo detected that you are trying to run a binary compiled for a different platform.\n\
               This usually happens when a macOS 'target' directory is mounted into a Linux container.\n\n\
               FIX: Run 'scripts/local-ci.sh --docker' to build fresh ELF binaries for Linux.\n\n",
            target, target_arch, current_os, current_arch
        );
        std::process::exit(1);
    }
}
