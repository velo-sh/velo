//! VELO-GOV-001 Audit Log Verification Tests
//!
//! RFC-0012 QA: Verify H-Gov audit log emission during fallback scenarios.

use velo::common::governance::{GovernanceSignal, SignalComponent};

/// Test that H-Gov audit output contains VELO-GOV-001 identifier
#[test]
fn test_hgov_audit_log_format() {
    let signal = GovernanceSignal::new(
        SignalComponent::MemoryGravity,
        "mmap failed: permission denied",
        "~50ms latency impact",
        "Check /dev/shm permissions",
    );

    let critical = signal.format_critical();

    // VELO-GOV-001: Critical format must contain key identifiers
    assert!(
        critical.contains("H-GOV CRITICAL:"),
        "Missing H-GOV CRITICAL prefix"
    );
    assert!(
        critical.contains("MemoryGravity"),
        "Missing component name"
    );
    assert!(
        critical.contains("strict_optimizations"),
        "Missing strict mode warning"
    );
}

/// Test that report_audit produces visible output
#[test]
fn test_hgov_audit_visible_output() {
    let signal = GovernanceSignal::new(
        SignalComponent::ZygoteIPC,
        "Socket connection timeout after 30s",
        "Request failed",
        "Restart Zygote daemon",
    );

    // report_audit writes to stderr - just verify it doesn't panic
    signal.report_audit();

    // The format should contain these elements
    let critical = signal.format_critical();
    assert!(critical.contains("Zygote/IPC"));
    assert!(critical.contains("30s"));
}

/// Test fallback signal creation for mmap failure
#[test]
fn test_hgov_mmap_fallback_signal() {
    // Simulate mmap failure scenario
    let signal = GovernanceSignal::from_python_error(
        "SHM-MMAP-001",
        "mmap failed: Cannot allocate memory",
        Some("velo-abc123"),
    );

    assert_eq!(signal.component, SignalComponent::MemoryGravity);
    assert!(signal.reason.contains("SHM-MMAP-001"));
    assert!(signal.reason.contains("mmap failed"));

    // Verify trace_id propagation
    assert_eq!(signal.trace_id.0, "velo-abc123");
}

/// Test that GovernanceSignal includes healing tips
#[test]
fn test_hgov_signal_healing_tip() {
    let signal = GovernanceSignal::new(
        SignalComponent::FastLoader,
        "Bundle corruption detected",
        "Slow import path",
        "Delete .velo/cache and rebuild",
    );

    let critical = signal.format_critical();
    assert!(
        critical.contains("Delete .velo/cache"),
        "Healing tip must be in output"
    );
}
