//! Zygote Circuit Breaker (SSOT-CB-001)
//!
//! Protects Velo from hanging or failing repeatedly when Zygote is misconfigured
//! or failing to start/respond.

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use std::path::PathBuf;

pub struct ZygoteCircuitBreaker;

impl ZygoteCircuitBreaker {
    /// Check if the circuit breaker is currently OPEN (tripped).
    pub fn is_tripped(config: &VeloConfig) -> bool {
        if !config.circuit_breaker_enabled {
            return false;
        }
        let path = VeloPaths::circuit_breaker_state();
        let failures = std::fs::read_to_string(&path)
            .ok()
            .and_then(|c| c.trim().parse::<u32>().ok());
        if let Some(f) = failures {
            return f >= config.circuit_breaker_threshold;
        }
        false
    }

    /// Record a failure in Zygote interaction (startup or IPC).
    pub fn record_failure(config: &VeloConfig) {
        if !config.circuit_breaker_enabled {
            return;
        }
        let path = VeloPaths::circuit_breaker_state();
        let current = std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| s.trim().parse::<u32>().ok())
            .unwrap_or(0);
        let failures = current + 1;
        let _ = std::fs::write(&path, failures.to_string());

        if failures >= config.circuit_breaker_threshold {
            let log_msg = format!(
                "🚨 Zygote Circuit Breaker TRIPPED after {} failures at {:?}. Falling back to direct spawn.",
                failures, path
            );
            log::error!("{}", log_msg);
            eprintln!("{}", log_msg);
        }
    }

    /// Record a successful interaction, resetting the failure counter.
    pub fn record_success() {
        let path = VeloPaths::circuit_breaker_state();
        if path.exists() {
            let _ = std::fs::remove_file(&path);
            let msg = format!(
                "✅ Zygote Circuit Breaker RESET at {:?}. Resuming Zygote forks.",
                path
            );
            log::info!("{}", msg);
            eprintln!("{}", msg);
        }
    }

    /// Get the path to the state file (for testing/diagnostics).
    pub fn state_file() -> PathBuf {
        VeloPaths::circuit_breaker_state()
    }
}
