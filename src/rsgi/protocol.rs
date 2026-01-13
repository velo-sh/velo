//! RSGI-Velo Protocol Definitions
//!
//! RFC-0019: Defines the binary exchange format between the Rust Host and Python Workers.
//! Uses MessagePack arrays for efficiency and cross-language compatibility.

use serde::{Deserialize, Serialize};

/// Message type IDs as defined in RFC-0019
pub const TYPE_REQ_START: u8 = 0x01;
pub const TYPE_REQ_BODY: u8 = 0x02;
pub const TYPE_RES_START: u8 = 0x03;
pub const TYPE_RES_BODY: u8 = 0x04;
pub const TYPE_KEEPALIVE: u8 = 0x09;
pub const TYPE_READY: u8 = 0x10;
pub const TYPE_AUTH_OK: u8 = 0x11;
/// Gate J: Host -> Worker: Initiate graceful shutdown
pub const TYPE_LIFESPAN_SHUTDOWN: u8 = 0x20;

/// Host -> Worker: Start a new request
/// [0x01, request_id, method, path, headers, has_body]
#[derive(Debug, Serialize, Deserialize)]
pub struct ReqStart(
    pub u8,
    pub u64,
    pub String,
    pub String,
    pub Vec<(String, String)>,
    pub bool,
    pub Option<(String, u16)>,
);

impl ReqStart {
    pub fn new(
        req_id: u64,
        method: String,
        path: String,
        headers: Vec<(String, String)>,
        has_body: bool,
        client: Option<(String, u16)>,
    ) -> Self {
        Self(
            TYPE_REQ_START,
            req_id,
            method,
            path,
            headers,
            has_body,
            client,
        )
    }
}

/// Host -> Worker: Send a chunk of request body
/// [0x02, request_id, chunk, is_eof]
#[derive(Debug, Serialize, Deserialize)]
pub struct ReqBody(pub u8, pub u64, pub Vec<u8>, pub bool);

impl ReqBody {
    pub fn new(id: u64, chunk: Vec<u8>, is_eof: bool) -> Self {
        Self(TYPE_REQ_BODY, id, chunk, is_eof)
    }
}

/// Worker -> Host: Send response status and headers
/// [0x03, request_id, status_code, headers]
#[derive(Debug, Serialize, Deserialize)]
pub struct ResStart(pub u8, pub u64, pub u16, pub Vec<(String, String)>);

/// Worker -> Host: Send a chunk of response body
/// [0x04, request_id, chunk, is_eof]
#[derive(Debug, Serialize, Deserialize)]
pub struct ResBody(pub u8, pub u64, pub Vec<u8>, pub bool);

/// Both: Ready to receive requests
/// [0x10, version, worker_id, capabilities, marshall_hints]
#[derive(Debug, Serialize, Deserialize)]
pub struct Ready(
    pub u8,
    pub String,
    pub String,
    pub serde_json::Value,
    pub serde_json::Value,
);

/// Both: Authentication/Handshake OK
/// [0x11, session_id, max_request_size]
#[derive(Debug, Serialize, Deserialize)]
pub struct AuthOk(pub u8, pub String, pub u64);

impl AuthOk {
    pub fn new() -> Self {
        Self(TYPE_AUTH_OK, "session-1".to_string(), 10 * 1024 * 1024)
    }
}

impl Default for AuthOk {
    fn default() -> Self {
        Self::new()
    }
}

/// Gate J: Host -> Worker: Initiate graceful shutdown
/// [0x20]
#[derive(Debug, Serialize, Deserialize)]
pub struct LifespanShutdown(pub u8);

impl LifespanShutdown {
    pub fn new() -> Self {
        Self(TYPE_LIFESPAN_SHUTDOWN)
    }
}

impl Default for LifespanShutdown {
    fn default() -> Self {
        Self::new()
    }
}

/// Message framing helpers
pub mod framing {
    use super::*;
    use crate::rsgi::{RSGIError, Result};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    pub async fn send_msg<T: Serialize, W: AsyncWriteExt + Unpin>(
        writer: &mut W,
        msg: &T,
    ) -> Result<()> {
        let payload = rmp_serde::to_vec(msg)?;
        let len = payload.len() as u32;
        writer.write_all(&len.to_be_bytes()).await?;
        writer.write_all(&payload).await?;
        Ok(())
    }

    pub async fn recv_msg<R: AsyncReadExt + Unpin>(reader: &mut R) -> Result<Vec<u8>> {
        let mut len_buf = [0u8; 4];
        reader.read_exact(&mut len_buf).await?;
        let len = u32::from_be_bytes(len_buf) as usize;

        if len > 10 * 1024 * 1024 {
            // 10MB limit
            return Err(RSGIError::Protocol(format!("Message too large: {}", len)));
        }

        let mut payload = vec![0u8; len];
        reader.read_exact(&mut payload).await?;
        Ok(payload)
    }
    #[cfg(test)]
    mod tests {
        use super::*;
        use std::io::Cursor;

        #[tokio::test]
        async fn test_send_recv_msg() {
            let mut buf = Vec::new();
            let msg = vec![1, 2, 3, 4];
            send_msg(&mut buf, &msg).await.unwrap();

            let mut reader = Cursor::new(buf);
            let out = recv_msg(&mut reader).await.unwrap();
            // send_msg/recv_msg works on raw payloads;
            // rmp_serde::to_vec of a Vec<u8> adds a MessagePack array prefix (0x94 for 4 elements).
            assert_eq!(out, rmp_serde::to_vec(&msg).unwrap());
        }

        #[tokio::test]
        async fn test_recv_msg_too_large() {
            let len: u32 = 11 * 1024 * 1024; // 11MB
            let mut buf = Vec::new();
            buf.extend_from_slice(&len.to_be_bytes());

            let mut reader = Cursor::new(buf);
            let result = recv_msg(&mut reader).await;
            // PROSECUTOR: Verify that the 10MB limit is strictly enforced.
            assert!(
                result.is_err(),
                "Framing MUST reject messages larger than 10MB"
            );
            if let Err(RSGIError::Protocol(e)) = result {
                assert!(e.contains("Message too large"));
            }
        }

        #[tokio::test]
        async fn test_recv_msg_truncated() {
            let mut buf = Vec::new();
            buf.extend_from_slice(&10u32.to_be_bytes());
            buf.extend_from_slice(&[1, 2, 3]); // Only 3 bytes of 10

            let mut reader = Cursor::new(buf);
            let result = recv_msg(&mut reader).await;
            assert!(result.is_err(), "Framing MUST fail on truncated messages");
        }
    }
}
