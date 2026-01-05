//! L7 Proxy Service - HTTP proxy to UDS workers
//!
//! RFC-0011 B.2.3: Implements the L7 proxy that routes HTTP requests to workers.
//!
//! ## Key Features
//!
//! - Load balances requests across UDS workers
//! - Injects X-Forwarded-* headers (RFC C.3)
//! - Strips hop-by-hop headers (RFC C.4)

use crate::proxy::UdsConnector;
use crate::proxy::load_balancer::{ConnectionGuard, LoadBalancer};
use crate::proxy::upstream::SocketTarget;
use http::{HeaderMap, HeaderValue, Request, header};
use hyper::Response;
use hyper::body::Incoming;
use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::Arc;
use thiserror::Error;
use tower_service::Service as TowerService;

/// Headers that MUST be stripped before forwarding (RFC 2616, Section 13.5.1).
///
/// RFC-0011 C.4 & 6A.3: These hop-by-hop headers could cause request smuggling if forwarded.
const HOP_BY_HOP_HEADERS: &[&str] = &[
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection", // RFC-0011 6A.3
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

/// Error type for proxy operations.
#[derive(Debug, Error)]
pub enum ProxyError {
    #[error("No healthy workers available")]
    NoHealthyWorkers,

    #[error("Failed to build request: {0}")]
    RequestBuild(#[from] http::Error),

    #[error("Failed to connect to worker: {0}")]
    Connection(String),

    #[error("Failed to forward request: {0}")]
    Forward(String),
}

/// L7 Proxy Service for routing HTTP requests to UDS workers.
///
/// RFC-0011 B.2.3: Implements load balancing and header injection.
#[derive(Clone)]
pub struct VeloProxyService {
    lb: Arc<LoadBalancer>,
}

impl VeloProxyService {
    /// Create a new proxy service with the given load balancer.
    pub fn new(lb: Arc<LoadBalancer>) -> Self {
        Self { lb }
    }

    /// Prepare a request for forwarding to a worker.
    ///
    /// This performs:
    /// 1. Load balancing to select a worker
    /// 2. Hop-by-hop header stripping (RFC C.4)
    /// 3. X-Forwarded-* header injection (RFC C.3)
    ///
    /// Returns the connection guard (for tracking) and the modified request.
    pub fn prepare_request(
        &self,
        mut req: Request<Incoming>,
        client_addr: Option<SocketAddr>,
    ) -> Result<(ConnectionGuard, Request<Incoming>), ProxyError> {
        // 1. Select worker via load balancer
        let guard = self
            .lb
            .select_worker()
            .ok_or(ProxyError::NoHealthyWorkers)?;

        // 2. Strip hop-by-hop headers (RFC C.4)
        Self::strip_hop_by_hop_headers(req.headers_mut());

        // 3. Inject X-Forwarded-* headers (RFC C.3)
        Self::inject_forwarded_headers(&mut req, client_addr);

        // 4. Inject X-Request-ID (RFC A.3)
        Self::inject_request_id(&mut req);

        // 5. Ensure W3C Trace Context (RFC B.3)
        Self::ensure_trace_context(&mut req);

        // 6. Add X-Velo-Worker header for debugging
        let socket_path = guard.socket_path();
        req.headers_mut().insert(
            "x-velo-worker",
            HeaderValue::from_str(socket_path).unwrap_or_else(|_| HeaderValue::from_static("")),
        );

        // 5. RFC-0011 O11y Review: Inject X-Request-ID for correlation
        let _request_id = Self::inject_request_id(&mut req);

        Ok((guard, req))
    }

    /// Strip hop-by-hop headers before forwarding.
    ///
    /// RFC-0011 C.4: Prevents HTTP request smuggling.
    pub fn strip_hop_by_hop_headers(headers: &mut HeaderMap) {
        // First, check for Connection header which may list additional hop-by-hop headers
        let connection_headers: Vec<String> = headers
            .get(header::CONNECTION)
            .and_then(|v| v.to_str().ok())
            .map(|s| {
                s.split(',')
                    .map(|h| h.trim().to_lowercase())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        // Remove standard hop-by-hop headers
        for header_name in HOP_BY_HOP_HEADERS {
            headers.remove(*header_name);
        }

        // Remove any headers listed in Connection header
        for header_name in &connection_headers {
            headers.remove(header_name.as_str());
        }
    }

    /// Inject X-Forwarded-* headers.
    ///
    /// RFC-0011 C.3: Required for ASGI apps to identify client.
    pub fn inject_forwarded_headers<B>(req: &mut Request<B>, client_addr: Option<SocketAddr>) {
        let headers = req.headers_mut();

        // X-Forwarded-For: Client IP address
        if let Some(addr) = client_addr {
            let client_ip = addr.ip().to_string();

            // Append to existing X-Forwarded-For or create new
            if let Some(existing) = headers.get("x-forwarded-for") {
                if let Ok(existing_str) = existing.to_str() {
                    let new_value = format!("{}, {}", existing_str, client_ip);
                    if let Ok(value) = HeaderValue::from_str(&new_value) {
                        headers.insert("x-forwarded-for", value);
                    }
                }
            } else if let Ok(value) = HeaderValue::from_str(&client_ip) {
                headers.insert("x-forwarded-for", value);
            }

            // X-Forwarded-Port: Client port
            let client_port = addr.port().to_string();
            if let Ok(value) = HeaderValue::from_str(&client_port) {
                headers.insert("x-forwarded-port", value);
            }
        }

        // X-Forwarded-Proto: Always HTTP for now (TLS termination is external)
        if !headers.contains_key("x-forwarded-proto") {
            headers.insert("x-forwarded-proto", HeaderValue::from_static("http"));
        }

        // X-Forwarded-Host: Preserve original Host header
        if let Some(host) = headers.get(header::HOST).cloned()
            && !headers.contains_key("x-forwarded-host")
        {
            headers.insert("x-forwarded-host", host);
        }
    }

    /// RFC-0011 O11y Review: Inject X-Request-ID for request correlation.
    ///
    /// If the request already has X-Request-ID, preserve it.
    /// Otherwise, generate a new UUID.
    ///
    /// Returns the request ID (for logging).
    pub fn inject_request_id<B>(req: &mut Request<B>) -> String {
        let headers = req.headers_mut();

        // Check if already present (from upstream proxy like nginx)
        if let Some(existing) = headers.get("x-request-id")
            && let Ok(id) = existing.to_str()
        {
            return id.to_string();
        }

        // Generate new UUID using thread-local random
        let request_id = generate_request_id();
        if let Ok(value) = HeaderValue::from_str(&request_id) {
            headers.insert("x-request-id", value);
        }

        request_id
    }

    /// RFC-0011 B.3: Ensure W3C Trace Context (traceparent).
    ///
    /// If `traceparent` is missing, generate a new valid W3C traceparent header.
    /// Format: 00-{trace_id}-{parent_id}-{flags}
    /// - trace_id: 32 hex chars
    /// - parent_id: 16 hex chars
    /// - flags: 01 (sampled)
    pub fn ensure_trace_context<B>(req: &mut Request<B>) {
        if !req.headers().contains_key("traceparent") {
            // Generate pseudo-random trace_id (using existing request_id if available for correlation)
            let request_id = req
                .headers()
                .get("x-request-id")
                .and_then(|h| h.to_str().ok())
                .unwrap_or("0000000000000000");

            // Pad request_id to 32 chars for trace_id (simple strategy)
            let trace_id = format!("{:0>32}", request_id);
            // Generate random parent_id
            let parent_id = format!(
                "{:016x}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_micros()
            );

            let traceparent = format!("00-{}-{}-01", trace_id, parent_id);

            if let Ok(val) = HeaderValue::from_str(&traceparent) {
                req.headers_mut().insert("traceparent", val);
            }
        }
    }

    /// Get the load balancer reference.
    pub fn load_balancer(&self) -> &LoadBalancer {
        &self.lb
    }
}

impl hyper::service::Service<Request<Incoming>> for VeloProxyService {
    type Response = Response<Incoming>;
    type Error = ProxyError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn call(&self, req: Request<Incoming>) -> Self::Future {
        let service = self.clone();

        Box::pin(async move {
            // 1. Prepare Request (Balancing & Headers)
            let (guard, proxy_req) = service.prepare_request(req, None)?;

            // 2. Connect to local UDS worker
            let socket_path_str = guard.socket_path();
            let mut connector = UdsConnector::new();
            let target = SocketTarget::from(socket_path_str);

            // 3. Connect (manual handshake for Phase 2B)
            // RFC-0011 Perf-001: Connection Pooling is deferred to Phase 3.
            // Current implementation uses "Connection-per-Request" for strict isolation and simplicity.
            let io = connector
                .call(target)
                .await
                .map_err(|e| ProxyError::Connection(e.to_string()))?;

            // 4. Send Request via Hyper
            let (mut sender, conn) = hyper::client::conn::http1::handshake(io)
                .await
                .map_err(|e| ProxyError::Connection(e.to_string()))?;

            // Spawn connection driver
            tokio::spawn(async move {
                if let Err(e) = conn.await {
                    let _ = e;
                }
            });

            // 5. Send Request
            let response = sender
                .send_request(proxy_req)
                .await
                .map_err(|e| ProxyError::Forward(e.to_string()))?;

            Ok(response)
        })
    }
}

/// Generate a request ID using timestamp and counter.
///
/// Format: 16 hex characters for request tracing
fn generate_request_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    // Mix timestamp + counter for uniqueness
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_micros() as u64)
        .unwrap_or(0);

    let count = COUNTER.fetch_add(1, Ordering::Relaxed);
    let hash = timestamp ^ (count << 48);

    format!("{:016x}", hash)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strip_hop_by_hop_headers() {
        let mut headers = HeaderMap::new();
        headers.insert(header::CONNECTION, HeaderValue::from_static("keep-alive"));
        headers.insert("keep-alive", HeaderValue::from_static("timeout=5"));
        headers.insert(
            header::TRANSFER_ENCODING,
            HeaderValue::from_static("chunked"),
        );
        headers.insert(header::HOST, HeaderValue::from_static("example.com"));
        headers.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/html"));

        VeloProxyService::strip_hop_by_hop_headers(&mut headers);

        // Hop-by-hop should be removed
        assert!(!headers.contains_key(header::CONNECTION));
        assert!(!headers.contains_key("keep-alive"));
        assert!(!headers.contains_key(header::TRANSFER_ENCODING));

        // End-to-end should be preserved
        assert!(headers.contains_key(header::HOST));
        assert!(headers.contains_key(header::CONTENT_TYPE));
    }

    #[test]
    fn test_strip_connection_listed_headers() {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::CONNECTION,
            HeaderValue::from_static("custom-header, another-header"),
        );
        headers.insert("custom-header", HeaderValue::from_static("value1"));
        headers.insert("another-header", HeaderValue::from_static("value2"));
        headers.insert("keep-header", HeaderValue::from_static("preserved"));

        VeloProxyService::strip_hop_by_hop_headers(&mut headers);

        // Headers listed in Connection should be removed
        assert!(!headers.contains_key("custom-header"));
        assert!(!headers.contains_key("another-header"));
        assert!(!headers.contains_key(header::CONNECTION));

        // Other headers should be preserved
        assert!(headers.contains_key("keep-header"));
    }

    #[test]
    fn test_proxy_service_creation() {
        let lb = Arc::new(LoadBalancer::new(vec!["/tmp/w1.sock".to_string()]));
        let service = VeloProxyService::new(lb);

        assert_eq!(service.load_balancer().worker_count(), 1);
    }

    // =========================================================================
    // RFC-0011 C.3: X-Forwarded-* Header Injection Tests
    // =========================================================================

    #[test]
    fn test_inject_x_forwarded_for_from_client_addr() {
        let mut req = Request::builder().uri("/api/test").body(()).unwrap();

        let client_addr: SocketAddr = "192.168.1.100:54321".parse().unwrap();
        VeloProxyService::inject_forwarded_headers(&mut req, Some(client_addr));

        // X-Forwarded-For should contain client IP
        let xff = req.headers().get("x-forwarded-for").unwrap();
        assert_eq!(xff.to_str().unwrap(), "192.168.1.100");
    }

    #[test]
    fn test_inject_x_forwarded_for_appends_to_existing() {
        let mut req = Request::builder()
            .uri("/api/test")
            .header("x-forwarded-for", "10.0.0.1, 10.0.0.2")
            .body(())
            .unwrap();

        let client_addr: SocketAddr = "192.168.1.100:54321".parse().unwrap();
        VeloProxyService::inject_forwarded_headers(&mut req, Some(client_addr));

        // Should append to existing chain
        let xff = req.headers().get("x-forwarded-for").unwrap();
        assert_eq!(xff.to_str().unwrap(), "10.0.0.1, 10.0.0.2, 192.168.1.100");
    }

    #[test]
    fn test_inject_x_forwarded_port() {
        let mut req = Request::builder().uri("/api/test").body(()).unwrap();

        let client_addr: SocketAddr = "192.168.1.100:54321".parse().unwrap();
        VeloProxyService::inject_forwarded_headers(&mut req, Some(client_addr));

        // X-Forwarded-Port should contain client port
        let xfp = req.headers().get("x-forwarded-port").unwrap();
        assert_eq!(xfp.to_str().unwrap(), "54321");
    }

    #[test]
    fn test_inject_x_forwarded_proto_default_http() {
        let mut req = Request::builder().uri("/api/test").body(()).unwrap();

        VeloProxyService::inject_forwarded_headers(&mut req, None);

        // Default proto should be "http"
        let xfproto = req.headers().get("x-forwarded-proto").unwrap();
        assert_eq!(xfproto.to_str().unwrap(), "http");
    }

    #[test]
    fn test_inject_x_forwarded_proto_preserves_existing() {
        let mut req = Request::builder()
            .uri("/api/test")
            .header("x-forwarded-proto", "https")
            .body(())
            .unwrap();

        VeloProxyService::inject_forwarded_headers(&mut req, None);

        // Should NOT overwrite existing proto
        let xfproto = req.headers().get("x-forwarded-proto").unwrap();
        assert_eq!(xfproto.to_str().unwrap(), "https");
    }

    #[test]
    fn test_inject_x_forwarded_host_from_host_header() {
        let mut req = Request::builder()
            .uri("/api/test")
            .header(header::HOST, "api.example.com")
            .body(())
            .unwrap();

        VeloProxyService::inject_forwarded_headers(&mut req, None);

        // X-Forwarded-Host should copy from Host header
        let xfhost = req.headers().get("x-forwarded-host").unwrap();
        assert_eq!(xfhost.to_str().unwrap(), "api.example.com");
    }

    // =========================================================================
    // RFC-0011 B.3: W3C Trace Context Tests
    // =========================================================================

    #[test]
    fn test_ensure_trace_context_generates_new() {
        let mut req = Request::builder().uri("/api/test").body(()).unwrap();

        VeloProxyService::ensure_trace_context(&mut req);

        let traceparent = req.headers().get("traceparent").unwrap();
        let value = traceparent.to_str().unwrap();

        // Format: 00-{trace_id}-{parent_id}-01
        assert!(value.starts_with("00-"));
        assert!(value.ends_with("-01"));
        assert_eq!(value.len(), 55); // 2 + 1 + 32 + 1 + 16 + 1 + 2
    }

    #[test]
    fn test_ensure_trace_context_preserves_existing() {
        let mut req = Request::builder()
            .uri("/api/test")
            .header(
                "traceparent",
                "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
            )
            .body(())
            .unwrap();

        VeloProxyService::ensure_trace_context(&mut req);

        let traceparent = req.headers().get("traceparent").unwrap();
        assert_eq!(
            traceparent.to_str().unwrap(),
            "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"
        );
    }
}
