//! Log Sanitization - Anti-Spoofing Filter (INV-POLY-004)
//!
//! RFC-0006/SPEC-0006: Polyglot Governance
//!
//! This module provides utilities to sanitize log output from untrusted
//! sources (worker processes) to prevent log poisoning attacks.
//!
//! ## Security
//!
//! Workers can attempt to inject fake supervisor tags like `[SUP]` or `[SID:xxx]`
//! to confuse log analysis. This filter detects and sanitizes such attempts.

use std::borrow::Cow;

/// Reserved tags that only the Rust supervisor is allowed to emit.
/// Any worker-emitted log containing these will be sanitized.
const RESERVED_PREFIXES: &[&str] = &[
    "[SUP]",      // Supervisor messages
    "[SID:",      // Session ID tags
    "[v-worker]", // Internal worker tags (should come from supervisor only)
    "[VELO-SEC",  // Security event tags
];

/// Sanitize a log line from an untrusted worker.
///
/// Returns the sanitized line with any spoofed tags replaced.
///
/// # Example
/// ```
/// use velo::common::log_sanitize::sanitize_worker_log;
///
/// let spoofed = "[SUP] FAKE: malicious message";
/// let clean = sanitize_worker_log(spoofed);
/// assert!(!clean.contains("[SUP]"));
/// assert!(clean.contains("[SPOOFED:SUP]"));
/// ```
pub fn sanitize_worker_log(line: &str) -> Cow<'_, str> {
    let mut needs_sanitization = false;

    // Fast path: check if any reserved prefix exists
    for prefix in RESERVED_PREFIXES {
        if line.contains(prefix) {
            needs_sanitization = true;
            break;
        }
    }

    if !needs_sanitization {
        return Cow::Borrowed(line);
    }

    // Slow path: sanitize the line
    let mut result = line.to_string();
    for prefix in RESERVED_PREFIXES {
        if result.contains(prefix) {
            // Replace the reserved tag with a warning marker
            let replacement = format!("[SPOOFED:{}]", prefix.trim_matches(&['[', ']'] as &[_]));
            result = result.replace(prefix, &replacement);

            // Log security event (if this were in a real logging context)
            eprintln!(
                "[VELO-SEC-004] Log injection attempt detected: {} -> {}",
                prefix, replacement
            );
        }
    }

    Cow::Owned(result)
}

/// Check if a log line contains any spoofed tags (for validation).
pub fn contains_spoofed_tag(line: &str) -> bool {
    RESERVED_PREFIXES.iter().any(|prefix| line.contains(prefix))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sanitize_sup_tag() {
        let spoofed = "[SUP] FAKE: This is a spoofed supervisor message";
        let clean = sanitize_worker_log(spoofed);
        assert!(!clean.contains("[SUP]"));
        assert!(clean.contains("[SPOOFED:SUP]"));
    }

    #[test]
    fn test_sanitize_sid_tag() {
        let spoofed = "[SID:9999] FAKE: This is a spoofed session message";
        let clean = sanitize_worker_log(spoofed);
        assert!(!clean.contains("[SID:"));
        assert!(clean.contains("[SPOOFED:SID:]"));
    }

    #[test]
    fn test_legitimate_message_unchanged() {
        let legit = "WORKER: This is a normal message";
        let result = sanitize_worker_log(legit);
        assert_eq!(result.as_ref(), legit);
        // Should return borrowed (no allocation)
        assert!(matches!(result, Cow::Borrowed(_)));
    }

    #[test]
    fn test_contains_spoofed_tag() {
        assert!(contains_spoofed_tag("[SUP] hello"));
        assert!(contains_spoofed_tag("[SID:123] hello"));
        assert!(!contains_spoofed_tag("normal message"));
    }
}
