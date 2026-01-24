//! RFC-0035: Preload Loader with "Death Pact" Sandbox (INV-PRELOAD-008)
//!
//! Implements safe loading of native libraries by first "vetting" them in a
//! child process. If the child process survives the `dlopen` call, the
//! parent assumes it's safe to load.

use anyhow::{Context, Result, bail};
use std::ffi::CString;
use std::path::Path;

#[cfg(unix)]
use libc::{RTLD_GLOBAL, RTLD_LOCAL, RTLD_NOW, WEXITSTATUS, WIFEXITED, c_int, fork, waitpid};

pub struct PreloadLoader;

impl PreloadLoader {
    /// Safe dlopen using a fork-sandbox (INV-PRELOAD-008)
    pub fn safe_load(path: &Path, global: bool) -> Result<()> {
        let path_str = path.to_str().context("Invalid library path encoding")?;
        let c_path = CString::new(path_str)?;

        let mut flags = RTLD_NOW | RTLD_LOCAL;
        if global {
            flags = RTLD_NOW | RTLD_GLOBAL;
        }

        #[cfg(unix)]
        unsafe {
            let pid = fork();
            if pid < 0 {
                bail!("Failed to fork for library vetting");
            }

            if pid == 0 {
                // --- Child Process ---
                // Attempt to load the library
                let handle = libc::dlopen(c_path.as_ptr(), flags);
                if handle.is_null() {
                    // We don't exit with error here because failing to load
                    // is different from crashing. A missing dependency
                    // should be handled gracefully, but a crash shouldn't
                    // kill the parent.
                    // However, RFC-0035 says we only load in parent if child survives.
                    std::process::exit(0);
                }
                // Handle Directive A: Intentional leak for process lifetime
                // We just exit successfully.
                std::process::exit(0);
            } else {
                // --- Parent Process ---
                let mut status: c_int = 0;
                let result = waitpid(pid, &mut status, 0);

                if result < 0 {
                    bail!("Failed to wait for vetting process");
                }

                if WIFEXITED(status) && WEXITSTATUS(status) == 0 {
                    // Child survived! Safe to load in parent.
                    let handle = libc::dlopen(c_path.as_ptr(), flags);
                    if handle.is_null() {
                        let err = libc::dlerror();
                        let err_msg = if err.is_null() {
                            "Unknown dlopen error".to_string()
                        } else {
                            std::ffi::CStr::from_ptr(err).to_string_lossy().into_owned()
                        };
                        bail!("Failed to load library in parent: {}", err_msg);
                    }
                    // Handle Directive A: No dlclose() - intentionally leak handle
                    Ok(())
                } else {
                    bail!(
                        "Death Pact: Library {:?} caused child process to crash or fail",
                        path
                    );
                }
            }
        }

        #[cfg(not(unix))]
        {
            bail!("Native preloading is only supported on Unix systems");
        }
    }

    /// Perform only the "Death Pact" vetting without loading in parent
    pub fn vett_only(path: &Path, global: bool) -> Result<()> {
        let path_str = path.to_str().context("Invalid library path encoding")?;
        let c_path = CString::new(path_str)?;

        let mut flags = RTLD_NOW | RTLD_LOCAL;
        if global {
            flags = RTLD_NOW | RTLD_GLOBAL;
        }

        #[cfg(unix)]
        unsafe {
            let pid = fork();
            if pid < 0 {
                bail!("Failed to fork for library vetting");
            }

            if pid == 0 {
                let handle = libc::dlopen(c_path.as_ptr(), flags);
                if handle.is_null() {
                    std::process::exit(1);
                }
                std::process::exit(0);
            } else {
                let mut status: c_int = 0;
                let result = waitpid(pid, &mut status, 0);

                if result < 0 {
                    bail!("Failed to wait for vetting process");
                }

                if WIFEXITED(status) && WEXITSTATUS(status) == 0 {
                    Ok(())
                } else {
                    bail!("Death Pact: Vetting failed for {:?}", path);
                }
            }
        }

        #[cfg(not(unix))]
        {
            bail!("Native preloading is only supported on Unix systems");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    #[cfg(unix)]
    fn test_death_pact_safety() {
        let _tmp = tempdir().unwrap();
        // We can't easily create a "crashing" .so in a unit test
        // without a compiler, but we can verify success path.
        // On macOS, we can try to load a system lib like libz.dylib
        #[cfg(target_os = "macos")]
        let lib_path = Path::new("/usr/lib/libz.dylib");
        #[cfg(target_os = "linux")]
        let lib_path = Path::new("/lib/x86_64-linux-gnu/libz.so.1");

        if lib_path.exists() {
            let result = PreloadLoader::safe_load(lib_path, false);
            assert!(
                result.is_ok(),
                "Should safely load system libz: {:?}",
                result.err()
            );
        }
    }

    #[test]
    fn test_non_existent_lib() {
        let path = Path::new("/tmp/non_existent_lib_random_name_123.so");
        let result = PreloadLoader::safe_load(path, false);
        assert!(result.is_err());
    }
}
