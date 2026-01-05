//! UDS Connector - Custom connector for Unix Domain Sockets
//!
//! RFC-0011 B.2.1: Allows Hyper to connect to Unix Domain Sockets.
//!
//! ## Design
//!
//! Since hyper's URI parsing doesn't support `unix://` scheme natively,
//! we store the socket path separately and use the connector to establish
//! connections based on that path.

use hyper_util::rt::TokioIo;
use std::future::Future;
use std::io;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use tokio::net::UnixStream;
use tower_service::Service;

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

/// A simple target type that just holds the socket path.
/// This is used as the request type for the Service trait.
#[derive(Clone, Debug)]
pub struct SocketTarget(pub PathBuf);

impl From<PathBuf> for SocketTarget {
    fn from(path: PathBuf) -> Self {
        Self(path)
    }
}

impl From<String> for SocketTarget {
    fn from(path: String) -> Self {
        Self(PathBuf::from(path))
    }
}

impl From<&str> for SocketTarget {
    fn from(path: &str) -> Self {
        Self(PathBuf::from(path))
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
        let path = target.0;

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
        assert_eq!(target.0, PathBuf::from("/tmp/test.sock"));
    }

    #[test]
    fn test_socket_target_from_string() {
        let target: SocketTarget = "/tmp/test.sock".into();
        assert_eq!(target.0, PathBuf::from("/tmp/test.sock"));
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
}
