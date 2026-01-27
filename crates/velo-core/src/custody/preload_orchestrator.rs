//! RFC-0035: Preload Orchestrator
//!
//! Orchestrates the verification and loading of libraries based on the
//! `preload.lock` file, supporting two-stage loading and RTLD promotion.

use crate::custody::native_fingerprint::{LoadStage, PreloadLock};
use crate::custody::preload_loader::PreloadLoader;
use crate::custody::preload_verifier::PreloadVerifier;
use anyhow::Result;
use std::path::Path;

pub struct PreloadOrchestrator {
    lock: PreloadLock,
    verifier: PreloadVerifier,
}

impl PreloadOrchestrator {
    pub fn new(lock: PreloadLock, venv_root: &Path) -> Self {
        Self {
            lock,
            verifier: PreloadVerifier::new(venv_root.to_path_buf()),
        }
    }

    /// Execute loading for a specific stage (INV-PRELOAD-009)
    pub fn load_stage(&self, stage: LoadStage, venv_root: &Path) -> Result<()> {
        for fp in &self.lock.fingerprints {
            if fp.load_stage == stage {
                let full_path = venv_root.join(&fp.relative_path);

                // 1. Path Validation (P2-001)
                let validated_path = self.verifier.validate_path(&full_path)?;

                // 2. Hash Verification with mtime fast-path (P2-002)
                if !fp.verify(&validated_path, false)? {
                    // INV-PRELOAD-007: Silent fallback on mismatch
                    log::warn!(
                        "Fingerprint mismatch for {:?}, skipping preload",
                        validated_path
                    );
                    continue;
                }

                // 3. Decide RTLD Mode (P2-005 / Directive B)
                let global = self.should_promote(&fp.soname);

                // 4. Safe Load via Death Pact (P2-003)
                if let Err(e) = PreloadLoader::safe_load(&validated_path, global) {
                    log::warn!("Preload failed for {:?}: {}", validated_path, e);
                }
            }
        }
        Ok(())
    }

    /// Directive B: Promote critical libraries to RTLD_GLOBAL
    fn should_promote(&self, soname: &str) -> bool {
        let soname = soname.to_lowercase();
        soname.starts_with("libtorch")
            || soname.starts_with("libtensorflow")
            || soname.starts_with("libpython")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_promotion_logic() {
        // We need a dummy lock for the orchestrator
        let lock = PreloadLock {
            version: "1.0".to_string(),
            generator: "test".to_string(),
            fingerprints: vec![],
        };
        let orch = PreloadOrchestrator::new(lock, Path::new("/tmp"));

        assert!(orch.should_promote("libtorch.so"));
        assert!(orch.should_promote("libtorch_cpu.so"));
        assert!(orch.should_promote("libpython3.10.so.1.0"));
        assert!(!orch.should_promote("libz.so"));
    }
}
