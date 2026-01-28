//! Proxy configuration for RFC-0011 L7 Proxy.
//!
//! This module provides configuration for the Velo proxy layer,
//! including timeout values from RFC-0011 Network SRE review.

use std::time::Duration;

/// RFC-0011 Network Review: Proxy timeout configuration.
///
/// Default values per Network SRE specification:
/// - header_timeout: 5s
/// - body_timeout: 60s
/// - upstream_timeout: 30s
#[derive(Debug, Clone)]
pub struct ProxyConfig {
    /// Max time to receive request headers (defense against Slowloris)
    pub header_timeout: Duration,

    /// Max time to receive request body
    pub body_timeout: Duration,

    /// Max time to wait for upstream (UDS worker) response
    pub upstream_timeout: Duration,

    /// Enable streaming (don't buffer entire body)
    pub streaming: bool,
}

impl Default for ProxyConfig {
    fn default() -> Self {
        Self {
            header_timeout: Duration::from_secs(5),    // RFC: 5s
            body_timeout: Duration::from_secs(60),     // RFC: 60s
            upstream_timeout: Duration::from_secs(30), // RFC: 30s
            streaming: true,                           // RFC: ensure streaming proxy
        }
    }
}

impl ProxyConfig {
    /// Create config with custom timeouts.
    pub fn new(
        header_timeout: Duration,
        body_timeout: Duration,
        upstream_timeout: Duration,
    ) -> Self {
        Self {
            header_timeout,
            body_timeout,
            upstream_timeout,
            streaming: true,
        }
    }

    /// Strict config for high-security environments.
    pub fn strict() -> Self {
        Self {
            header_timeout: Duration::from_secs(3),
            body_timeout: Duration::from_secs(30),
            upstream_timeout: Duration::from_secs(15),
            streaming: true,
        }
    }

    /// Lenient config for long-running requests (AI inference, etc.)
    pub fn lenient() -> Self {
        Self {
            header_timeout: Duration::from_secs(10),
            body_timeout: Duration::from_secs(300), // 5 minutes
            upstream_timeout: Duration::from_secs(300), // 5 minutes
            streaming: true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_proxy_config_default_values() {
        let config = ProxyConfig::default();
        assert_eq!(config.header_timeout, Duration::from_secs(5));
        assert_eq!(config.body_timeout, Duration::from_secs(60));
        assert_eq!(config.upstream_timeout, Duration::from_secs(30));
        assert!(config.streaming);
    }

    #[test]
    fn test_proxy_config_strict() {
        let config = ProxyConfig::strict();
        assert!(config.header_timeout < Duration::from_secs(5));
        assert!(config.upstream_timeout < Duration::from_secs(30));
    }

    #[test]
    fn test_proxy_config_lenient() {
        let config = ProxyConfig::lenient();
        assert!(config.body_timeout >= Duration::from_secs(300));
        assert!(config.upstream_timeout >= Duration::from_secs(300));
    }

    #[test]
    fn test_proxy_config_custom() {
        let config = ProxyConfig::new(
            Duration::from_secs(10),
            Duration::from_secs(120),
            Duration::from_secs(60),
        );
        assert_eq!(config.header_timeout, Duration::from_secs(10));
        assert_eq!(config.body_timeout, Duration::from_secs(120));
        assert_eq!(config.upstream_timeout, Duration::from_secs(60));
    }
}
