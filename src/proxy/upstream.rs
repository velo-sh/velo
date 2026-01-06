//! UDS Connector - Custom connector for Unix Domain Sockets
//!
//! RFC-0011 B.2.1: Allows Hyper to connect to Unix Domain Sockets.
//!
//! ## Design
//!
//! Since hyper's URI parsing doesn't support `unix://` scheme natively,
//! we store the socket path separately and use the connector to establish
//! connections based on that path.
//!
//! ## Buffer Tuning (RFC-0011 D.3)
//!
//! For high-throughput local IPC, socket buffers should be sized appropriately.
//! Default system buffers (often 64KB) can cause excess context switches.
//! We recommend 256KB for UDS connections.

use hyper_util::rt::TokioIo;
use std::future::Future;
use std::io;
use std::os::unix::io::AsRawFd;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use tokio::net::UnixStream;
use tower_service::Service;

/// RFC-0011 D.3: Recommended buffer size for high-throughput UDS connections.
/// 256KB reduces context switches for local IPC.
pub const RECOMMENDED_UDS_BUFFER_SIZE: usize = 256 * 1024; // 256KB

/// RFC-0011 D.2: Connection pool configuration for UDS.
///
/// Default Hyper config is tuned for WAN, not local UDS.
/// These settings are optimized for local IPC performance.
#[derive(Debug, Clone)]
pub struct UdsPoolConfig {
    /// Idle connection timeout in seconds (RFC recommends 30s+ for UDS)
    pub pool_idle_timeout_secs: u64,

    /// Max idle connections per worker socket (1 is optimal for UDS)
    pub pool_max_idle_per_host: usize,

    /// Socket buffer size in bytes (RFC recommends 256KB)
    pub socket_buffer_size: usize,
}

impl Default for UdsPoolConfig {
    fn default() -> Self {
        Self {
            pool_idle_timeout_secs: 30, // RFC D.2 recommendation
            pool_max_idle_per_host: 1,  // RFC D.2: 1 per worker socket
            socket_buffer_size: RECOMMENDED_UDS_BUFFER_SIZE,
        }
    }
}

impl UdsPoolConfig {
    /// Create a new config with custom values.
    pub fn new(idle_timeout: u64, max_idle: usize, buffer_size: usize) -> Self {
        Self {
            pool_idle_timeout_secs: idle_timeout,
            pool_max_idle_per_host: max_idle,
            socket_buffer_size: buffer_size,
        }
    }

    /// Create a high-performance config for local IPC.
    pub fn high_performance() -> Self {
        Self {
            pool_idle_timeout_secs: 60,
            pool_max_idle_per_host: 2,
            socket_buffer_size: 512 * 1024, // 512KB for very high throughput
        }
    }
}

/// Connection target for Unix Domain Sockets.
///
/// Instead of encoding socket path in URI, we pass it directly.
#[derive(Clone, Debug)]
pub struct UdsTarget {
    /// Path to the Unix socket
    pub socket_path: PathBuf,
}

impl UdsTarget {
    /// Create a new UDS target from a socket path.
    pub fn new<P: Into<PathBuf>>(path: P) -> Self {
        Self {
            socket_path: path.into(),
        }
    }
}

/// Custom Connector allowing Hyper to connect to Unix Domain Sockets.
///
/// RFC-0011 B.2.1: Connects to UDS targets using the socket path directly.
#[derive(Clone, Debug, Default)]
pub struct UdsConnector {
    /// Target socket path (set when a connection is made)
    target: Option<Arc<PathBuf>>,
}

impl UdsConnector {
    /// Create a new UDS connector.
    pub fn new() -> Self {
        Self { target: None }
    }

    /// Create a connector with a specific target socket.
    pub fn with_target<P: Into<PathBuf>>(path: P) -> Self {
        Self {
            target: Some(Arc::new(path.into())),
        }
    }

    /// Set the target socket path.
    pub fn set_target<P: Into<PathBuf>>(&mut self, path: P) {
        self.target = Some(Arc::new(path.into()));
    }

    /// Extract socket path from the target.
    pub fn socket_path(&self) -> Option<&PathBuf> {
        self.target.as_ref().map(|arc| arc.as_ref())
    }
}

/// RFC-0011 D.3: Set socket buffer sizes for high-throughput UDS.
///
/// For local IPC, larger buffers reduce context switches and improve throughput.
/// This function sets both send and receive buffers to the specified size.
///
/// # Arguments
/// * `stream` - Unix stream (must implement AsRawFd)
/// * `buffer_size` - Buffer size in bytes (recommend `RECOMMENDED_UDS_BUFFER_SIZE`)
///
/// # Errors
/// Returns io::Error if setsockopt fails (rare on Unix systems).
#[cfg(unix)]
pub fn set_socket_buffer_sizes<S: AsRawFd>(stream: &S, buffer_size: usize) -> io::Result<()> {
    let fd = stream.as_raw_fd();
    let size = buffer_size as libc::c_int;

    // Set send buffer (SO_SNDBUF)
    let result = unsafe {
        libc::setsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_SNDBUF,
            &size as *const libc::c_int as *const libc::c_void,
            std::mem::size_of::<libc::c_int>() as libc::socklen_t,
        )
    };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }

    // Set receive buffer (SO_RCVBUF)
    let result = unsafe {
        libc::setsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_RCVBUF,
            &size as *const libc::c_int as *const libc::c_void,
            std::mem::size_of::<libc::c_int>() as libc::socklen_t,
        )
    };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }

    Ok(())
}

/// RFC-0011 D.3: Get current socket buffer sizes.
///
/// Returns (send_buffer, recv_buffer) in bytes.
#[cfg(unix)]
pub fn get_socket_buffer_sizes<S: AsRawFd>(stream: &S) -> io::Result<(usize, usize)> {
    let fd = stream.as_raw_fd();
    let mut size: libc::c_int = 0;
    let mut len = std::mem::size_of::<libc::c_int>() as libc::socklen_t;

    // Get send buffer size
    let result = unsafe {
        libc::getsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_SNDBUF,
            &mut size as *mut libc::c_int as *mut libc::c_void,
            &mut len,
        )
    };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    let send_buf = size as usize;

    // Get receive buffer size
    let result = unsafe {
        libc::getsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_RCVBUF,
            &mut size as *mut libc::c_int as *mut libc::c_void,
            &mut len,
        )
    };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    let recv_buf = size as usize;

    Ok((send_buf, recv_buf))
}

/// Error type for UDS connector operations.
#[derive(Debug, thiserror::Error)]
pub enum UdsConnectorError {
    #[error("No socket target configured")]
    NoTarget,

    #[error("IO error connecting to socket: {0}")]
    Io(#[from] io::Error),
}

/// Future returned by UdsConnector.
pub struct UdsConnectFuture {
    inner: Pin<Box<dyn Future<Output = Result<TokioIo<UnixStream>, UdsConnectorError>> + Send>>,
}

impl Future for UdsConnectFuture {
    type Output = Result<TokioIo<UnixStream>, UdsConnectorError>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.inner.as_mut().poll(cx)
    }
}

/// RFC-0011 Master Review: Worker target with unique URI authority.
///
/// **Red Line**: Hyper connection pool routes by URI authority.
/// Without unique authority per worker, requests route to WRONG worker.
///
/// Each SocketTarget has a worker_id that generates unique authority:
/// `worker-{id}@velo`
#[derive(Clone, Debug)]
pub struct SocketTarget {
    /// Path to the Unix socket
    pub socket_path: PathBuf,
    /// Worker ID for unique URI authority
    pub worker_id: u64,
}

impl SocketTarget {
    /// Create a new socket target with worker ID.
    pub fn new<P: Into<PathBuf>>(path: P, worker_id: u64) -> Self {
        Self {
            socket_path: path.into(),
            worker_id,
        }
    }

    /// Generate unique URI authority for Hyper connection pooling.
    ///
    /// Format: `worker-{id}@velo`
    ///
    /// This ensures each worker gets its own connection pool entry.
    pub fn authority(&self) -> String {
        format!("worker-{}@velo", self.worker_id)
    }
}

impl From<PathBuf> for SocketTarget {
    fn from(path: PathBuf) -> Self {
        Self {
            socket_path: path,
            worker_id: 0, // Default for compatibility
        }
    }
}

impl From<String> for SocketTarget {
    fn from(path: String) -> Self {
        Self {
            socket_path: PathBuf::from(path),
            worker_id: 0,
        }
    }
}

impl From<&str> for SocketTarget {
    fn from(path: &str) -> Self {
        Self {
            socket_path: PathBuf::from(path),
            worker_id: 0,
        }
    }
}

impl Service<SocketTarget> for UdsConnector {
    type Response = TokioIo<UnixStream>;
    type Error = UdsConnectorError;
    type Future = UdsConnectFuture;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, target: SocketTarget) -> Self::Future {
        let path = target.socket_path;

        UdsConnectFuture {
            inner: Box::pin(async move {
                let stream = UnixStream::connect(&path).await?;
                Ok(TokioIo::new(stream))
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_uds_target_creation() {
        let target = UdsTarget::new("/tmp/velo-worker-1.sock");
        assert_eq!(target.socket_path, PathBuf::from("/tmp/velo-worker-1.sock"));
    }

    #[test]
    fn test_socket_target_from_pathbuf() {
        let target: SocketTarget = PathBuf::from("/tmp/test.sock").into();
        assert_eq!(target.socket_path, PathBuf::from("/tmp/test.sock"));
        assert_eq!(target.worker_id, 0); // Default
    }

    #[test]
    fn test_socket_target_from_string() {
        let target: SocketTarget = "/tmp/test.sock".into();
        assert_eq!(target.socket_path, PathBuf::from("/tmp/test.sock"));
        assert_eq!(target.worker_id, 0);
    }

    // =========================================================================
    // RFC-0011 Master Review: Unique URI Authority Tests
    // =========================================================================

    #[test]
    fn test_socket_target_new_with_worker_id() {
        let target = SocketTarget::new("/tmp/worker-42.sock", 42);
        assert_eq!(target.socket_path, PathBuf::from("/tmp/worker-42.sock"));
        assert_eq!(target.worker_id, 42);
    }

    #[test]
    fn test_socket_target_authority_unique_per_worker() {
        let target1 = SocketTarget::new("/tmp/w1.sock", 1);
        let target2 = SocketTarget::new("/tmp/w2.sock", 2);
        let target3 = SocketTarget::new("/tmp/w3.sock", 3);

        assert_eq!(target1.authority(), "worker-1@velo");
        assert_eq!(target2.authority(), "worker-2@velo");
        assert_eq!(target3.authority(), "worker-3@velo");

        // Authorities must be unique
        assert_ne!(target1.authority(), target2.authority());
        assert_ne!(target2.authority(), target3.authority());
    }

    #[test]
    fn test_uds_connector_with_target() {
        let connector = UdsConnector::with_target("/tmp/test.sock");
        assert_eq!(
            connector.socket_path(),
            Some(&PathBuf::from("/tmp/test.sock"))
        );
    }

    #[test]
    fn test_uds_connector_set_target() {
        let mut connector = UdsConnector::new();
        assert!(connector.socket_path().is_none());

        connector.set_target("/tmp/test.sock");
        assert_eq!(
            connector.socket_path(),
            Some(&PathBuf::from("/tmp/test.sock"))
        );
    }

    // =========================================================================
    // TDD Cycle 2.3: Async UDS Connection Test
    // =========================================================================

    #[tokio::test]
    async fn test_uds_connector_connects_to_real_socket() {
        use std::os::unix::net::UnixListener;
        use tempfile::TempDir;
        use tower_service::Service;

        // Create temp socket
        let temp_dir = TempDir::new().unwrap();
        let socket_path = temp_dir.path().join("test.sock");

        // Start a listener
        let _listener = UnixListener::bind(&socket_path).unwrap();

        // Connect via our connector
        let mut connector = UdsConnector::new();
        let target = SocketTarget::from(socket_path.clone());

        let result = connector.call(target).await;
        assert!(result.is_ok(), "Should connect to socket: {:?}", result);
    }

    #[tokio::test]
    async fn test_uds_connector_fails_on_nonexistent_socket() {
        use tower_service::Service;

        let mut connector = UdsConnector::new();
        let target = SocketTarget::from("/tmp/nonexistent-velo-test-12345.sock");

        let result = connector.call(target).await;
        assert!(result.is_err(), "Should fail on nonexistent socket");
    }

    // =========================================================================
    // RFC-0011 D.3: Buffer Tuning Tests
    // =========================================================================

    #[test]
    fn test_recommended_buffer_size_constant() {
        // Verify the constant matches RFC recommendation (256KB)
        assert_eq!(RECOMMENDED_UDS_BUFFER_SIZE, 256 * 1024);
        assert_eq!(RECOMMENDED_UDS_BUFFER_SIZE, 262144);
    }

    #[tokio::test]
    async fn test_set_and_get_socket_buffer_sizes() {
        use std::os::unix::net::UnixListener;
        use tempfile::TempDir;

        // Create temp socket
        let temp_dir = TempDir::new().unwrap();
        let socket_path = temp_dir.path().join("buffer-test.sock");
        let _listener = UnixListener::bind(&socket_path).unwrap();

        // Connect
        let stream = tokio::net::UnixStream::connect(&socket_path).await.unwrap();

        // Set buffer sizes to 128KB
        let target_size = 128 * 1024;
        let result = set_socket_buffer_sizes(&stream, target_size);
        assert!(result.is_ok(), "Should set buffer sizes: {:?}", result);

        // Get and verify (kernel may double the value, so just check it's larger)
        let (send_buf, recv_buf) = get_socket_buffer_sizes(&stream).unwrap();
        assert!(
            send_buf >= target_size,
            "Send buffer should be at least {}: got {}",
            target_size,
            send_buf
        );
        assert!(
            recv_buf >= target_size,
            "Recv buffer should be at least {}: got {}",
            target_size,
            recv_buf
        );
    }
}
