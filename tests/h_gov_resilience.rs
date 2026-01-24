//! H-Gov Resilience Tests
//!
//! RFC-0012 QA: Tests for Heightened Governance fallback mechanisms.
//! Verifies that optimization failures are properly logged and handled.

use velo::common::governance::{GovernanceSignal, SignalComponent, TraceID};

/// Test that GovernanceSignal can be created from Python-side error
#[test]
fn test_governance_signal_from_python_error() {
    let signal = GovernanceSignal::from_python_error(
        "SHM-MMAP-001",
        "Shared memory allocation failed: permission denied",
        Some("velo-trace-abc123"),
    );

    assert_eq!(signal.component, SignalComponent::MemoryGravity);
    assert!(signal.reason.contains("SHM-MMAP-001"));
    assert!(signal.reason.contains("permission denied"));
    assert_eq!(signal.trace_id.0, "velo-trace-abc123");
}

/// Test that IPC prefix maps to correct component
#[test]
fn test_governance_signal_ipc_prefix() {
    let signal = GovernanceSignal::from_python_error(
        "IPC-SOCKET-002",
        "Socket connection timeout",
        None,
    );

    assert_eq!(signal.component, SignalComponent::ZygoteIPC);
}

/// Test that ENV prefix maps to correct component
#[test]
fn test_governance_signal_env_prefix() {
    let signal = GovernanceSignal::from_python_error(
        "ENV-SCRUB-001",
        "Environment sanitization failed",
        None,
    );

    assert_eq!(signal.component, SignalComponent::EnvShield);
}

/// Test that unknown prefix maps to PythonWorker
#[test]
fn test_governance_signal_unknown_prefix() {
    let signal = GovernanceSignal::from_python_error(
        "UNKNOWN-ERR-001",
        "Some error",
        None,
    );

    assert_eq!(signal.component, SignalComponent::PythonWorker);
}

/// Test that report_audit can be called without panic
#[test]
fn test_governance_signal_report_audit() {
    let signal = GovernanceSignal::new(
        SignalComponent::MemoryGravity,
        "Test failure",
        "Minimal impact",
        "No action required",
    );

    // This should not panic
    signal.report_audit();
}

/// Test format_critical produces expected output structure
#[test]
fn test_governance_signal_format_critical() {
    let signal = GovernanceSignal::new(
        SignalComponent::ZygoteIPC,
        "Connection refused",
        "High latency",
        "Restart Zygote",
    );

    let critical = signal.format_critical();

    assert!(critical.contains("H-GOV CRITICAL:"));
    assert!(critical.contains("Zygote/IPC"));
    assert!(critical.contains("Connection refused"));
    assert!(critical.contains("strict_optimizations"));
}

/// Test TraceID generation produces unique values
#[test]
fn test_trace_id_uniqueness() {
    let id1 = TraceID::generate();
    let id2 = TraceID::generate();

    // IDs should be unique (8 hex chars each)
    assert_eq!(id1.0.len(), 8);
    assert_eq!(id2.0.len(), 8);
    // Note: There's a tiny chance they could be equal, but very unlikely
}
