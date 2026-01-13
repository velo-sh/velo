//! RSGI Host Implementation
//!
//! RFC-0019: Native Sovereignty.
//! Implements the Rust-native host that manages Python workers and dispatches
//! requests using the RSGI-Velo protocol.

use crate::proxy::load_balancer::LoadBalancer;
use crate::rsgi::{RSGIError, Result, protocol};
use bytes::Bytes;
use http_body_util::{BodyExt, StreamBody};
use hyper::body::{Frame, Incoming};
use hyper::service::Service;
use hyper::{Request, Response};
use std::pin::Pin;
use std::sync::Arc;
use tokio::net::UnixStream;
use uuid::Uuid;

/// RSGI Host Engine
#[derive(Clone)]
pub struct RSGIHost {
    lb: Arc<LoadBalancer>,
}

impl RSGIHost {
    pub fn new(lb: Arc<LoadBalancer>) -> Self {
        Self { lb }
    }

    pub fn with_client_addr(self, _addr: std::net::SocketAddr) -> Self {
        self
    }

    /// Perform RSGI handshake with a worker (RFC-0019 v1.0)
    async fn perform_handshake(stream: &mut UnixStream, lb: &LoadBalancer) -> Result<()> {
        // Gate H: Peer Authentication (DEF-72-H01)
        // SEC-07-001: Validate UID AND PID from peer credentials
        #[cfg(unix)]
        {
            let creds = stream.peer_cred()?;
            let current_uid = unsafe { libc::getuid() };

            // Step 1: UID must match (same user)
            if creds.uid() != current_uid {
                eprintln!(
                    "RSGI Gate H: Security Violation - UID mismatch: peer={} expected={}",
                    creds.uid(),
                    current_uid
                );
                return Err(RSGIError::HandshakeFailed(format!(
                    "Security Violation: Peer UID {} mismatch (expected {})",
                    creds.uid(),
                    current_uid
                )));
            }

            // Step 2: PID must be in authorized registry (anti-hijack)
            if let Some(peer_pid) = creds.pid()
                && !lb.is_authorized_pid(peer_pid as u32)
            {
                eprintln!(
                    "RSGI Gate H: Security Violation - Unauthorized PID {} (not in worker registry)",
                    peer_pid
                );
                return Err(RSGIError::HandshakeFailed(format!(
                    "Security Violation: PID {} not authorized (possible hijack attempt)",
                    peer_pid
                )));
            }
        }

        // Gate E: Lifecycle Timeout (500ms)
        let handshake_future = async {
            // 1. Wait for READY from worker
            let payload = protocol::framing::recv_msg(stream).await?;
            let ready: protocol::Ready = rmp_serde::from_slice(&payload)?;

            if ready.0 != protocol::TYPE_READY {
                // DEF-72-E03: Log malformed READY for observability
                eprintln!("Expected READY, got type {}", ready.0);
                return Err(RSGIError::HandshakeFailed(format!(
                    "Expected READY, got type {}",
                    ready.0
                )));
            }

            // 2. Send AUTH_OK
            let auth_ok = protocol::AuthOk(
                protocol::TYPE_AUTH_OK,
                Uuid::now_v7().to_string(),
                1024 * 1024 * 10, // 10MB default
            );
            protocol::framing::send_msg(stream, &auth_ok).await?;
            Ok(())
        };

        tokio::time::timeout(tokio::time::Duration::from_millis(500), handshake_future)
            .await
            .map_err(|_| {
                // DEF-72-E02: Log timeout for observability
                eprintln!("Handshake timed out after 500ms");
                RSGIError::Timeout("Handshake timed out after 500ms".to_string())
            })?
    }
}

impl Service<Request<Incoming>> for RSGIHost {
    type Response = Response<BoxBody<Bytes, RSGIError>>;
    type Error = RSGIError;
    type Future =
        Pin<Box<dyn Future<Output = std::result::Result<Self::Response, Self::Error>> + Send>>;

    fn call(&self, req: Request<Incoming>) -> Self::Future {
        let lb = self.lb.clone();

        Box::pin(async move {
            // 1. Select worker
            let guard = lb
                .select_worker()
                .ok_or_else(|| RSGIError::Protocol("No healthy workers available".to_string()))?;

            let socket_path = guard.socket_path();

            // 2. Connect to worker
            let mut stream = UnixStream::connect(socket_path).await?;

            // 3. Handshake (Gate H: validates worker PID)
            Self::perform_handshake(&mut stream, &lb).await?;

            // 4. Send Request Headers (ReqStart)
            let (parts, body) = req.into_parts();
            let method = parts.method.to_string();
            let path = parts.uri.path().to_string();
            let headers: Vec<(String, String)> = parts
                .headers
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
                .collect();
            let req_id: u64 = 1; // Handled per-stream

            // Always assume body may be present; streaming handles empty case
            let req_start = protocol::ReqStart::new(req_id, method, path, headers, true);
            protocol::framing::send_msg(&mut stream, &req_start).await?;

            // 5. Send Request Body
            {
                let mut body = body;
                while let Some(frame_result) = body.frame().await {
                    let frame = frame_result
                        .map_err(|e| RSGIError::Protocol(format!("Hyper body error: {}", e)))?;
                    if let Ok(data) = frame.into_data() {
                        let req_body = protocol::ReqBody::new(req_id, data.to_vec(), false);
                        protocol::framing::send_msg(&mut stream, &req_body).await?;
                    }
                }
                // Send EOF
                let req_eof = protocol::ReqBody::new(req_id, vec![], true);
                protocol::framing::send_msg(&mut stream, &req_eof).await?;
            }

            // 6. Receive Response Start (ResStart)
            let payload = protocol::framing::recv_msg(&mut stream).await?;
            let res_start: protocol::ResStart = rmp_serde::from_slice(&payload)?;

            if res_start.0 != protocol::TYPE_RES_START {
                return Err(RSGIError::Protocol(format!(
                    "Expected RES_START, got type {}",
                    res_start.0
                )));
            }

            let mut res_builder = Response::builder().status(res_start.2);

            for (k, v) in res_start.3 {
                res_builder = res_builder.header(k, v);
            }

            // 7. Receive Response Body (Streaming)
            let (body_tx, body_stream) = tokio::sync::mpsc::channel(1);

            tokio::spawn(async move {
                loop {
                    match protocol::framing::recv_msg(&mut stream).await {
                        Ok(payload) => {
                            match rmp_serde::from_slice::<protocol::ResBody>(&payload) {
                                Ok(res_body) => {
                                    if !res_body.2.is_empty() {
                                        let _ = body_tx
                                            .send(Ok(Frame::data(Bytes::from(res_body.2))))
                                            .await;
                                    }
                                    if res_body.3 {
                                        // is_eof
                                        break;
                                    }
                                }
                                Err(e) => {
                                    let _ = body_tx.send(Err(RSGIError::Deserialization(e))).await;
                                    break;
                                }
                            }
                        }
                        Err(e) => {
                            let _ = body_tx.send(Err(e)).await;
                            break;
                        }
                    }
                }
            });

            let body = StreamBody::new(tokio_stream::wrappers::ReceiverStream::new(body_stream));

            Ok(res_builder.body(body.boxed()).unwrap())
        })
    }
}

pub type BoxBody<D, E> = http_body_util::combinators::BoxBody<D, E>;

impl Default for RSGIHost {
    fn default() -> Self {
        Self::new(Arc::new(LoadBalancer::new(vec![])))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[tokio::test]
    async fn test_rsgi_handshake() {
        let dir = tempdir().unwrap();
        let socket_path = dir.path().join("test.sock");
        // 1. Start mock worker
        let listener = tokio::net::UnixListener::bind(&socket_path).unwrap();
        tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();

            // Send READY
            let ready = protocol::Ready(
                protocol::TYPE_READY,
                "1.0.0".into(),
                "worker-1".into(),
                serde_json::Value::Null,
                serde_json::Value::Null,
            );
            protocol::framing::send_msg(&mut stream, &ready)
                .await
                .unwrap();

            // Recv AUTH_OK
            let payload = protocol::framing::recv_msg(&mut stream).await.unwrap();
            let auth_ok: protocol::AuthOk = rmp_serde::from_slice(&payload).unwrap();
            assert_eq!(auth_ok.0, protocol::TYPE_AUTH_OK);
        });

        // 2. Connect and handshake via RSGIHost
        // Create LoadBalancer with current process PID registered for Gate H
        let lb = LoadBalancer::new(vec![socket_path.to_string_lossy().to_string()]);
        let current_pid = std::process::id();
        lb.register_worker_pid(0, current_pid);

        let mut stream = UnixStream::connect(&socket_path).await.unwrap();
        RSGIHost::perform_handshake(&mut stream, &lb)
            .await
            .expect("Handshake should succeed");
    }
}
