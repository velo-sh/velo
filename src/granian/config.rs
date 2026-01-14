//! Worker Configuration
//!
//! Configuration types for Granian workers.

use std::time::Duration;

/// Configuration for a Granian RSGI worker.
#[derive(Debug, Clone)]
pub struct WorkerConfig {
    /// Worker ID (unique per worker)
    pub worker_id: i32,

    /// Socket file descriptor to listen on
    pub socket_fd: i32,

    /// Path to ASGI application (e.g., "main:app")
    pub app_path: String,

    /// Enable WebSocket support
    pub websockets_enabled: bool,

    /// Number of Tokio threads per worker
    pub threads: usize,

    /// Maximum blocking threads
    pub blocking_threads: usize,

    /// Number of Python threads
    pub py_threads: usize,

    /// Python thread idle timeout (seconds)
    pub py_threads_idle_timeout: u64,

    /// Backpressure limit (max pending connections)
    pub backpressure: usize,

    /// HTTP mode: "1", "2", or "auto"
    pub http_mode: String,

    /// TLS configuration (None = no TLS)
    pub tls_config: Option<TlsConfig>,
}

impl Default for WorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: 0,
            socket_fd: -1,
            app_path: String::new(),
            websockets_enabled: true,
            threads: 1,
            blocking_threads: 512,
            py_threads: 1,
            py_threads_idle_timeout: 30,
            backpressure: 256,
            http_mode: "auto".to_string(),
            tls_config: None,
        }
    }
}

impl WorkerConfig {
    /// Create a new worker configuration with required fields.
    pub fn new(worker_id: i32, socket_fd: i32, app_path: impl Into<String>) -> Self {
        Self {
            worker_id,
            socket_fd,
            app_path: app_path.into(),
            ..Default::default()
        }
    }

    /// Set WebSocket support.
    pub fn with_websockets(mut self, enabled: bool) -> Self {
        self.websockets_enabled = enabled;
        self
    }

    /// Set HTTP mode ("1", "2", or "auto").
    pub fn with_http_mode(mut self, mode: impl Into<String>) -> Self {
        self.http_mode = mode.into();
        self
    }

    /// Set TLS configuration.
    pub fn with_tls(mut self, config: TlsConfig) -> Self {
        self.tls_config = Some(config);
        self
    }

    /// Set thread counts.
    pub fn with_threads(mut self, threads: usize, blocking: usize, py: usize) -> Self {
        self.threads = threads;
        self.blocking_threads = blocking;
        self.py_threads = py;
        self
    }
}

/// TLS configuration for worker.
#[derive(Debug, Clone)]
pub struct TlsConfig {
    /// Path to certificate file
    pub cert_path: String,

    /// Path to private key file
    pub key_path: String,

    /// Optional password for private key
    pub key_password: Option<String>,

    /// Minimum TLS protocol version (e.g., "1.2", "1.3")
    pub protocol_min: String,

    /// Optional CA certificate path for client verification
    pub ca_path: Option<String>,

    /// CRL paths for certificate revocation
    pub crl_paths: Vec<String>,

    /// Require client certificate verification
    pub client_verify: bool,
}

impl Default for TlsConfig {
    fn default() -> Self {
        Self {
            cert_path: String::new(),
            key_path: String::new(),
            key_password: None,
            protocol_min: "1.3".to_string(),
            ca_path: None,
            crl_paths: Vec::new(),
            client_verify: false,
        }
    }
}

/// HTTP/1.1 specific configuration.
#[derive(Debug, Clone)]
pub struct Http1Config {
    /// Header read timeout
    pub header_read_timeout: Duration,

    /// Keep connections alive
    pub keep_alive: bool,

    /// Maximum buffer size
    pub max_buffer_size: usize,

    /// Pipeline flush
    pub pipeline_flush: bool,
}

impl Default for Http1Config {
    fn default() -> Self {
        Self {
            header_read_timeout: Duration::from_secs(30),
            keep_alive: true,
            max_buffer_size: 65536,
            pipeline_flush: false,
        }
    }
}

/// HTTP/2 specific configuration.
#[derive(Debug, Clone)]
pub struct Http2Config {
    /// Adaptive window sizing
    pub adaptive_window: bool,

    /// Initial connection window size
    pub initial_connection_window_size: u32,

    /// Initial stream window size
    pub initial_stream_window_size: u32,

    /// Keep-alive interval
    pub keep_alive_interval: Option<Duration>,

    /// Keep-alive timeout
    pub keep_alive_timeout: Duration,

    /// Maximum concurrent streams
    pub max_concurrent_streams: u32,

    /// Maximum frame size
    pub max_frame_size: u32,

    /// Maximum headers size
    pub max_headers_size: u32,

    /// Maximum send buffer size
    pub max_send_buffer_size: usize,
}

impl Default for Http2Config {
    fn default() -> Self {
        Self {
            adaptive_window: false,
            initial_connection_window_size: 1024 * 1024, // 1MB
            initial_stream_window_size: 1024 * 1024,     // 1MB
            keep_alive_interval: None,
            keep_alive_timeout: Duration::from_secs(20),
            max_concurrent_streams: 200,
            max_frame_size: 16384,
            max_headers_size: 16384,
            max_send_buffer_size: 1024 * 1024, // 1MB
        }
    }
}
