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

/// A unique identifier for a specific optimization attempt to allow forensic correlation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TraceID(pub String);

impl fmt::Display for TraceID {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl TraceID {
    /// Generate a new TraceID from seed (usually worker ID or project hash)
    pub fn generate() -> Self {
        use std::time::{SystemTime, UNIX_EPOCH};
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let hash = blake3::hash(&now.to_le_bytes());
        Self(hex::encode(&hash.as_bytes()[..4])) // 8 hex chars
    }
}

/// A structured governance signal representing an optimization failure
pub struct GovernanceSignal {
    pub component: SignalComponent,
    pub reason: String,
    pub impact_estimate: &'static str,
    pub healing_tip: &'static str,
    pub trace_id: TraceID,
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
            trace_id: TraceID::generate(),
        }
    }

    /// Report as a high-visibility audit log (Prod/Relaxed Mode)
    pub fn report_audit(&self) {
        eprintln!(
            "⚠️ {} [{}] Optimization '{}' failed: {}\n\
             📊 {} {}\n\
             🔧 {} {}",
            "H-GOV AUDIT:".yellow().bold(),
            self.trace_id.to_string().bright_black(),
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
            "🚨 {} [{}] Optimization '{}' failed to initialize.\n\
             Reason: {}\n\
             Impact: {}\n\
             Healing Tip: {}\n\
             Note: Fallback is blocked (strict_optimizations=true) to prevent silent regressions.",
            "H-GOV CRITICAL:".red().bold(),
            self.trace_id.to_string().bright_magenta(),
            self.component,
            self.reason,
            self.impact_estimate,
            self.healing_tip
        )
    }
}

/// Specialized error type for Velo optimization failures (RFC-0012)
#[derive(Debug)]
pub struct VeloOptimizationError {
    pub signal: GovernanceSignal,
}

impl VeloOptimizationError {
    pub fn new(signal: GovernanceSignal) -> Self {
        Self { signal }
    }
}

impl fmt::Display for VeloOptimizationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.signal.format_critical())
    }
}

impl std::error::Error for VeloOptimizationError {}

impl fmt::Debug for GovernanceSignal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("GovernanceSignal")
            .field("component", &self.component)
            .field("reason", &self.reason)
            .field("trace_id", &self.trace_id)
            .finish()
    }
}
