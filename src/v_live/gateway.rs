//! Vibe WebSocket Gateway (RFC-0029)
//!
//! Native Rust implementation for broadcasting worker results as JSON.

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use once_cell::sync::Lazy;
use serde_json::Value;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::broadcast;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::protocol::Message;

/// Hard limit for outgoing frames (5MB)
const MAX_FRAME_SIZE: usize = 5 * 1024 * 1024;

/// Global broadcast channel for Vibe messages
static BROADCAST_CHANNEL: Lazy<(broadcast::Sender<Value>, broadcast::Receiver<Value>)> =
    Lazy::new(|| broadcast::channel(1024));

pub struct VibeGateway {
    addr: String,
}

impl VibeGateway {
    pub fn new(addr: &str) -> Self {
        Self {
            addr: addr.to_string(),
        }
    }

    /// Broadcast a JSON message to all connected clients.
    pub async fn broadcast(msg: Value) {
        let (tx, _) = &*BROADCAST_CHANNEL;
        let _ = tx.send(msg);
    }

    /// Get a receiver for the broadcast channel.
    pub fn subscribe(&self) -> broadcast::Receiver<Value> {
        let (tx, _) = &*BROADCAST_CHANNEL;
        tx.subscribe()
    }

    /// Run the gateway server.
    pub async fn run(&self) -> Result<()> {
        let listener = TcpListener::bind(&self.addr)
            .await
            .with_context(|| format!("Failed to bind Vibe Gateway to {}", self.addr))?;

        log::info!("Vibe Gateway listening on {}", self.addr);

        loop {
            let (stream, _) = listener.accept().await?;
            let tx = self.subscribe();

            tokio::spawn(async move {
                if let Err(e) = Self::handle_connection(stream, tx).await {
                    log::error!("Gateway connection error: {:?}", e);
                }
            });
        }
    }

    async fn handle_connection(
        stream: TcpStream,
        mut rx: broadcast::Receiver<Value>,
    ) -> Result<()> {
        let mut ws_stream = accept_async(stream)
            .await
            .context("Error during WebSocket handshake")?;

        loop {
            tokio::select! {
                // Handle broadcast messages
                msg_val = rx.recv() => {
                    match msg_val {
                        Ok(val) => {
                            let json_str = serde_json::to_string(&val)?;
                            if json_str.len() > MAX_FRAME_SIZE {
                                log::warn!("Skipping large vibe frame ({} bytes)", json_str.len());
                                continue;
                            }
                            ws_stream.send(Message::Text(json_str)).await?;
                        }
                        Err(broadcast::error::RecvError::Lagged(n)) => {
                            log::warn!("Gateway client lagged by {} messages", n);
                        }
                        Err(broadcast::error::RecvError::Closed) => break,
                    }
                }
                // Handle client messages (heartbeats, etc)
                msg_ws = ws_stream.next() => {
                    match msg_ws {
                        Some(Ok(Message::Ping(p))) => {
                            ws_stream.send(Message::Pong(p)).await?;
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        _ => {} // Ignore other messages for now
                    }
                }
            }
        }

        Ok(())
    }
}
