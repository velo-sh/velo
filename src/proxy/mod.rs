//! L7 Proxy module for Velo worker management
//!
//! RFC-0011: Implements HTTP proxy to route external requests to UDS workers.
//!
//! ## Architecture
//!
//! ```text
//! External HTTP → TCP Port → L7 Proxy → LoadBalancer → UDS Worker
//! ```

pub mod config;
pub mod load_balancer;
pub mod service;
pub mod upstream;

pub use config::ProxyConfig;
pub use load_balancer::{ConnectionGuard, LoadBalancer, WorkerNode};
pub use service::VeloProxyService;
pub use upstream::{SocketTarget, UdsConnector, UdsPoolConfig, UdsTarget};
