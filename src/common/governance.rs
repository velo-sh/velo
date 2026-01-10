//! H-Gov (Heightened Governance) Structured Signals
//!
//! Provides the data structures and methods for reporting optimization
//! failures and fallbacks (H-Gov Audit) across the Velo codebase.

use colored::Colorize;
use std::fmt;

/// Category of the failing optimization
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalComponent {
    ZygoteIPC,
    MemoryGravity,
    NumaAffinity,
    EnvShield,
    FastLoader,
}

impl fmt::Display for SignalComponent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            Self::ZygoteIPC => "Zygote/IPC",
            Self::MemoryGravity => "MemoryGravity/SHM",
            Self::NumaAffinity => "NUMA/Affinity",
            Self::EnvShield => "EnvShield/Scrubbing",
            Self::FastLoader => "FastLoader/Bundle",
        };
        write!(f, "{}", s)
    }
}

/// A structured governance signal representing an optimization failure
pub struct GovernanceSignal {
    pub component: SignalComponent,
    pub reason: String,
    pub impact_estimate: &'static str,
    pub healing_tip: &'static str,
}

impl GovernanceSignal {
    /// Create a new signal
    pub fn new(
        component: SignalComponent,
        reason: impl Into<String>,
        impact: &'static str,
        tip: &'static str,
    ) -> Self {
        Self {
            component,
            reason: reason.into(),
            impact_estimate: impact,
            healing_tip: tip,
        }
    }

    /// Report as a high-visibility audit log (Prod/Relaxed Mode)
    pub fn report_audit(&self) {
        eprintln!(
            "⚠️ {} Optimization '{}' failed: {}\n\
             📊 {} {}\n\
             🔧 {} {}",
            "H-GOV AUDIT:".yellow().bold(),
            self.component,
            self.reason,
            "Impact:".cyan().bold(),
            self.impact_estimate,
            "Healing:".green().bold(),
            self.healing_tip
        );
    }

    /// Format as a fatal error message (Dev/CI Mode)
    pub fn format_critical(&self) -> String {
        format!(
            "🚨 {} Optimization '{}' failed to initialize.\n\
             Reason: {}\n\
             Impact: {}\n\
             Healing Tip: {}\n\
             Note: Fallback is blocked (strict_optimizations=true) to prevent silent regressions.",
            "H-GOV CRITICAL:".red().bold(),
            self.component,
            self.reason,
            self.impact_estimate,
            self.healing_tip
        )
    }
}
