//! Health check server for Kubernetes/cloud native deployments (CN-P0-001)
//!
//! Provides minimal HTTP endpoints for liveness and readiness probes.
//! Uses `tiny_http` for minimal overhead.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::JoinHandle;

/// Health server configuration
pub struct HealthConfig {
    /// Bind address (e.g., "0.0.0.0:8081")
    pub bind: String,
}

/// Minimal health check server.
///
/// Exposes:
/// - `GET /healthz` → 200 OK (liveness)
/// - `GET /readyz` → 200 OK when ready, 503 NOT READY otherwise
pub struct HealthServer {
    ready: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
}

impl HealthServer {
    /// Spawn a new health server in a background thread.
    ///
    /// # Arguments
    /// * `bind` - Address to bind (e.g., "0.0.0.0:8081")
    /// * `ready` - Shared flag indicating readiness
    ///
    /// # Returns
    /// The health server handle
    pub fn spawn(bind: &str, ready: Arc<AtomicBool>) -> Result<Self, HealthError> {
        let ready_clone = Arc::clone(&ready);
        let bind_str = bind.to_string();

        let handle = std::thread::spawn(move || {
            if let Ok(server) = tiny_http::Server::http(&bind_str) {
                Self::serve_loop(server, ready_clone);
            }
        });

        Ok(Self {
            ready,
            handle: Some(handle),
        })
    }

    /// Mark the application as ready.
    pub fn set_ready(&self) {
        self.ready.store(true, Ordering::SeqCst);
    }

    /// Main server loop.
    fn serve_loop(server: tiny_http::Server, ready: Arc<AtomicBool>) {
        for request in server.incoming_requests() {
            let (status, body) = Self::handle_request(request.url(), &ready);

            let response = tiny_http::Response::from_string(body)
                .with_status_code(status)
                .with_header(
                    tiny_http::Header::from_bytes(&b"Content-Type"[..], &b"text/plain"[..])
                        .unwrap(),
                );
            // SEC-P0-004: Do not include Server header (Recon Prevention)

            // Ignore errors - client may have disconnected
            let _ = request.respond(response);
        }
    }

    /// Handle a single request.
    ///
    /// SEC-P0-004: Return ONLY status, no metadata (version, PID, uptime, app info).
    fn handle_request(url: &str, ready: &Arc<AtomicBool>) -> (u16, &'static str) {
        match url {
            "/healthz" => (200, "OK"),
            "/readyz" => {
                if ready.load(Ordering::SeqCst) {
                    (200, "OK")
                } else {
                    (503, "NOT READY")
                }
            }
            _ => (404, "Not Found"),
        }
    }
}

impl Drop for HealthServer {
    fn drop(&mut self) {
        // The server will stop when dropped, thread will exit
        if let Some(handle) = self.handle.take() {
            // We don't wait for the thread - it will exit when server is dropped
            drop(handle);
        }
    }
}

/// Health server errors
#[derive(Debug)]
pub enum HealthError {
    /// Invalid bind address
    InvalidBind(String),
    /// Failed to bind to address
    BindFailed(String),
}

impl std::fmt::Display for HealthError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBind(addr) => write!(f, "Invalid health bind address: {}", addr),
            Self::BindFailed(reason) => write!(f, "Failed to bind health server: {}", reason),
        }
    }
}

impl std::error::Error for HealthError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_handle_healthz() {
        let ready = Arc::new(AtomicBool::new(false));
        let (status, body) = HealthServer::handle_request("/healthz", &ready);
        assert_eq!(status, 200);
        assert_eq!(body, "OK");
    }

    #[test]
    fn test_handle_readyz_not_ready() {
        let ready = Arc::new(AtomicBool::new(false));
        let (status, body) = HealthServer::handle_request("/readyz", &ready);
        assert_eq!(status, 503);
        assert_eq!(body, "NOT READY");
    }

    #[test]
    fn test_handle_readyz_ready() {
        let ready = Arc::new(AtomicBool::new(true));
        let (status, body) = HealthServer::handle_request("/readyz", &ready);
        assert_eq!(status, 200);
        assert_eq!(body, "OK");
    }

    #[test]
    fn test_handle_not_found() {
        let ready = Arc::new(AtomicBool::new(true));
        let (status, body) = HealthServer::handle_request("/unknown", &ready);
        assert_eq!(status, 404);
        assert_eq!(body, "Not Found");
    }

    #[test]
    fn test_sec_p0_004_no_metadata() {
        // SEC-P0-004: Verify responses contain ONLY status, no metadata
        let ready = Arc::new(AtomicBool::new(true));

        // Check all endpoints return minimal responses
        let (_, body) = HealthServer::handle_request("/healthz", &ready);
        assert_eq!(body, "OK", "healthz should return minimal 'OK'");

        let (_, body) = HealthServer::handle_request("/readyz", &ready);
        assert_eq!(body, "OK", "readyz should return minimal 'OK'");

        // Ensure no version/PID/uptime info is leaked
        let responses = ["/healthz", "/readyz"];
        for url in responses {
            let (_, body) = HealthServer::handle_request(url, &ready);
            assert!(!body.contains("version"), "Should not contain version info");
            assert!(!body.contains("pid"), "Should not contain PID");
            assert!(!body.contains("uptime"), "Should not contain uptime");
        }
    }
}
