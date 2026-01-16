//! L7 Proxy Service - HTTP proxy to UDS workers
//!
//! RFC-0011 B.2.3: Implements the L7 proxy that routes HTTP requests to workers.
//!
//! ## Key Features
//!
//! - Load balances requests across UDS workers
//! - Injects X-Forwarded-* headers (RFC C.3)
//! - Strips hop-by-hop headers (RFC C.4)

use crate::proxy::load_balancer::{ConnectionGuard, LoadBalancer};
use http::{HeaderMap, HeaderValue, Request, header};
use hyper::Response;
use hyper::body::Incoming;
use hyper_util::rt::TokioIo;
use std::future::Future;
use std::net::SocketAddr;
#[cfg(target_os = "macos")]
use std::os::unix::io::AsRawFd;
use std::pin::Pin;
use std::sync::Arc;
use thiserror::Error;
use tokio::net::UnixStream;

/// Headers that MUST be stripped before forwarding (RFC 2616, Section 13.5.1).
///
/// RFC-0011 C.4 & 6A.3: These hop-by-hop headers could cause request smuggling if forwarded.
const HOP_BY_HOP_HEADERS: &[header::HeaderName] = &[
    header::CONNECTION,
    header::PROXY_AUTHENTICATE,
    header::PROXY_AUTHORIZATION,
    header::TE,
    header::TRAILER,
    header::TRANSFER_ENCODING,
    header::UPGRADE,
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
/// RFC-0011 §6A.7: Uses Per-Worker Client architecture.
/// Each worker has a dedicated client, load balancing happens per request.
#[derive(Clone)]
pub struct VeloProxyService {
    lb: Arc<LoadBalancer>,
}

impl VeloProxyService {
    /// Create a new proxy service with the given load balancer.
    ///
    /// RFC-0011 §6A.7: Creates Per-Worker Client architecture.
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
    pub fn prepare_request<B>(
        &self,
        mut req: Request<B>,
        client_addr: Option<SocketAddr>,
    ) -> Result<(ConnectionGuard, Request<B>), ProxyError> {
        // 1. Select worker via load balancer
        let guard = self
            .lb
            .select_worker()
            .ok_or(ProxyError::NoHealthyWorkers)?;

        // 2. Strip hop-by-hop headers (RFC C.4)
        Self::strip_hop_by_hop_headers(req.headers_mut());

        // 3. Inject X-Forwarded-* headers (RFC C.3)
        Self::inject_forwarded_headers(&mut req, client_addr);

        // 4. Inject correlation headers (RFC A.3, B.3)
        Self::inject_request_id(&mut req);
        Self::ensure_trace_context(&mut req);

        // 5. Add X-Velo-Worker header for debugging/QA verification (Worker side)
        let socket_path = guard.socket_path();
        req.headers_mut().insert(
            "x-velo-worker",
            HeaderValue::from_str(&socket_path).unwrap_or_else(|_| HeaderValue::from_static("")),
        );

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

        // 1. Remove standard hop-by-hop headers
        for header_name in HOP_BY_HOP_HEADERS {
            if headers.remove(header_name).is_some() {
                eprintln!("[PROXY] Stripped standard hop-by-hop: {:?}", header_name);
            }
        }

        // 2. Remove non-standard or missing Hyper constants
        for h in ["keep-alive", "proxy-connection"] {
            if let Ok(hn) = header::HeaderName::from_bytes(h.as_bytes()) {
                headers.remove(hn);
            }
        }

        // 3. Remove any headers listed in Connection header
        for header_name_str in &connection_headers {
            if let Ok(hn) = header::HeaderName::from_bytes(header_name_str.as_bytes()) {
                headers.remove(hn);
            }
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

    /// Create a service instance bound to a specific client address.
    ///
    /// RFC-0011 BLOCK-004 Fix: This allows X-Forwarded-For injection with actual client IP.
    pub fn with_client_addr(self, client_addr: SocketAddr) -> VeloProxyServiceWithAddr {
        VeloProxyServiceWithAddr {
            inner: self,
            client_addr,
        }
    }
}

/// Wrapper service that carries the client's socket address for header injection.
///
/// This is necessary because `hyper::service::Service::call()` doesn't provide
/// access to the underlying connection's peer address.
#[derive(Clone)]
pub struct VeloProxyServiceWithAddr {
    inner: VeloProxyService,
    client_addr: SocketAddr,
}

impl hyper::service::Service<Request<Incoming>> for VeloProxyServiceWithAddr {
    type Response = Response<Incoming>;
    type Error = ProxyError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn call(&self, req: Request<Incoming>) -> Self::Future {
        let proxy = self.inner.clone();
        let client_addr = self.client_addr;

        Box::pin(async move {
            // Use standardized preparation logic (RFC-0011 §6A.7)
            let (guard, proxy_req) = proxy.prepare_request(req, Some(client_addr))?;
            let worker_socket_path = guard.socket_path().to_string();

            // Connect directly to worker socket (Standardized UDS path)
            let stream = UnixStream::connect(&worker_socket_path)
                .await
                .map_err(|e| {
                    ProxyError::Connection(format!(
                        "UDS connect failed to {}: {}",
                        worker_socket_path, e
                    ))
                })?;

            // Gate H (DEF-72-H01): Peer Authentication for Legacy mode
            {
                let creds = stream
                    .peer_cred()
                    .map_err(|e| ProxyError::Connection(e.to_string()))?;
                let current_uid = unsafe { libc::getuid() };
                if creds.uid() != current_uid {
                    return Err(ProxyError::Connection(format!(
                        "Security Violation: UID mismatch (expected {})",
                        current_uid
                    )));
                }

                #[allow(unused_mut)]
                let mut peer_pid = creds.pid();
                #[cfg(target_os = "macos")]
                if peer_pid.is_none() || peer_pid == Some(0) {
                    let fd = stream.as_raw_fd();
                    if peer_pid.is_none() {
                        let mut pid: libc::pid_t = 0;
                        let mut len = std::mem::size_of::<libc::pid_t>() as libc::socklen_t;
                        unsafe {
                            if libc::getsockopt(fd, 0, 0x01, &mut pid as *mut _ as *mut _, &mut len)
                                == 0
                            {
                                peer_pid = Some(pid);
                            }
                        }
                    }
                }

                if let Some(pid) = peer_pid
                    && pid != 0
                    && !proxy.load_balancer().is_authorized_pid(pid as u32)
                {
                    return Err(ProxyError::Connection(format!(
                        "Security Violation: PID {} not authorized",
                        pid
                    )));
                }
            }

            let io = TokioIo::new(stream);

            // HTTP/1.1 handshake
            let (mut sender, conn) = hyper::client::conn::http1::handshake(io)
                .await
                .map_err(|e| ProxyError::Connection(format!("HTTP handshake failed: {}", e)))?;

            // Spawn connection driver
            tokio::spawn(async move {
                if let Err(_e) = conn.await {
                    // Connection closed
                }
            });

            // Send request
            let result = sender.send_request(proxy_req).await;

            match result {
                Ok(mut res) => {
                    guard.record_success();
                    // DEF-72-E01: Strip hop-by-hop headers from RESPONSE
                    VeloProxyService::strip_hop_by_hop_headers(res.headers_mut());
                    // Inject diagnostic header into RESPONSE for QA verification (Client side)
                    res.headers_mut().insert(
                        "x-velo-worker",
                        HeaderValue::from_str(&worker_socket_path)
                            .unwrap_or_else(|_| HeaderValue::from_static("error")),
                    );
                    Ok(res)
                }
                Err(e) => {
                    guard.record_failure();
                    Err(ProxyError::Forward(e.to_string()))
                }
            }
        })
    }
}

impl hyper::service::Service<Request<Incoming>> for VeloProxyService {
    type Response = Response<Incoming>;
    type Error = ProxyError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn call(&self, req: Request<Incoming>) -> Self::Future {
        let proxy = self.clone();

        Box::pin(async move {
            // Use standardized preparation logic (RFC-0011 §6A.7)
            let (guard, proxy_req) = proxy.prepare_request(req, None)?;
            let worker_socket_path = guard.socket_path().to_string();
            eprintln!("[PROXY] call: routing to {}", worker_socket_path);

            // Connect directly to worker socket (Standardized UDS path)
            let stream = UnixStream::connect(&worker_socket_path)
                .await
                .map_err(|e| {
                    ProxyError::Connection(format!(
                        "UDS connect failed to {}: {}",
                        worker_socket_path, e
                    ))
                })?;

            // Gate H (DEF-72-H01): Peer Authentication for Legacy mode
            {
                let creds = stream
                    .peer_cred()
                    .map_err(|e| ProxyError::Connection(e.to_string()))?;
                let current_uid = unsafe { libc::getuid() };
                if creds.uid() != current_uid {
                    return Err(ProxyError::Connection(format!(
                        "Security Violation: UID mismatch (expected {})",
                        current_uid
                    )));
                }

                #[allow(unused_mut)]
                let mut peer_pid = creds.pid();
                #[cfg(target_os = "macos")]
                if peer_pid.is_none() {
                    let fd = stream.as_raw_fd();
                    let mut pid: libc::pid_t = 0;
                    let mut len = std::mem::size_of::<libc::pid_t>() as libc::socklen_t;
                    unsafe {
                        // SOL_LOCAL = 0, LOCAL_PEERPID = 0x01
                        if libc::getsockopt(fd, 0, 0x01, &mut pid as *mut _ as *mut _, &mut len)
                            == 0
                        {
                            peer_pid = Some(pid);
                        }
                    }
                }

                if let Some(pid) = peer_pid
                    && !proxy.load_balancer().is_authorized_pid(pid as u32)
                {
                    return Err(ProxyError::Connection(format!(
                        "Security Violation: PID {} not authorized",
                        pid
                    )));
                }
            }

            let io = TokioIo::new(stream);

            // HTTP/1.1 handshake
            let (mut sender, conn) = hyper::client::conn::http1::handshake(io)
                .await
                .map_err(|e| ProxyError::Connection(format!("HTTP handshake failed: {}", e)))?;

            // Spawn connection driver
            tokio::spawn(async move {
                if let Err(_e) = conn.await {
                    // Connection closed
                }
            });

            // Send request
            let result = sender.send_request(proxy_req).await;

            match result {
                Ok(mut res) => {
                    guard.record_success();
                    // DEF-72-E01: Strip hop-by-hop headers from RESPONSE
                    Self::strip_hop_by_hop_headers(res.headers_mut());
                    // Inject diagnostic header into RESPONSE for QA verification (Client side)
                    res.headers_mut().insert(
                        "x-velo-worker",
                        HeaderValue::from_str(&worker_socket_path)
                            .unwrap_or_else(|_| HeaderValue::from_static("error")),
                    );
                    Ok(res)
                }
                Err(e) => {
                    guard.record_failure();
                    Err(ProxyError::Forward(e.to_string()))
                }
            }
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
        let lb = Arc::new(LoadBalancer::new(vec![
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .to_string(),
        ]));
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
