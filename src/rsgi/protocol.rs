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
);

impl ReqStart {
    pub fn new(
        id: u64,
        method: String,
        path: String,
        headers: Vec<(String, String)>,
        has_body: bool,
    ) -> Self {
        Self(TYPE_REQ_START, id, method, path, headers, has_body)
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
/// [0x10, version, worker_id, capabilities]
#[derive(Debug, Serialize, Deserialize)]
pub struct Ready(pub u8, pub String, pub String, pub serde_json::Value);

/// Both: Authentication/Handshake OK
/// [0x11, session_id, max_request_size]
#[derive(Debug, Serialize, Deserialize)]
pub struct AuthOk(pub u8, pub String, pub u64);
