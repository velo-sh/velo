//! Vibe WebSocket Gateway (RFC-0029)
//!
//! Native Rust implementation for broadcasting worker results as JSON.

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::Value;
use std::path::PathBuf;
use std::time::SystemTime;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::broadcast;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::protocol::Message;

/// Hard limit for outgoing frames (5MB)
const MAX_FRAME_SIZE: usize = 5 * 1024 * 1024;

/// Global broadcast channel for Vibe messages
static BROADCAST_CHANNEL: Lazy<(broadcast::Sender<Value>, broadcast::Receiver<Value>)> =
    Lazy::new(|| broadcast::channel(1024));

/// Store last result with timestamp for late joiners (RFC-0029 Pillar 6)
static LAST_RESULT: Lazy<Mutex<Option<(Value, SystemTime)>>> = Lazy::new(|| Mutex::new(None));

pub struct VibeGateway {
    addr: String,
    target: PathBuf,
}

impl VibeGateway {
    pub fn new(addr: &str, target: PathBuf) -> Self {
        Self {
            addr: addr.to_string(),
            target,
        }
    }

    /// Broadcast a JSON message to all connected clients.
    pub fn broadcast_sync(msg: Value) {
        {
            let mut last = LAST_RESULT.lock();
            *last = Some((msg.clone(), SystemTime::now()));
        }

        let (tx, _) = &*BROADCAST_CHANNEL;
        let _ = tx.send(msg);
    }

    /// Clear the cached result (called at start of new execution).
    pub fn clear_last_result() {
        let mut last = LAST_RESULT.lock();
        *last = None;
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
            let target = self.target.clone();

            tokio::spawn(async move {
                if let Err(e) = Self::handle_connection(stream, tx, target).await {
                    log::error!("Gateway connection error: {:?}", e);
                }
            });
        }
    }

    async fn handle_connection(
        stream: TcpStream,
        mut rx: broadcast::Receiver<Value>,
        target: PathBuf,
    ) -> Result<()> {
        let mut ws_stream = accept_async(stream)
            .await
            .context("Error during WebSocket handshake")?;

        // Send last result immediately to late joiners (DEF-08-004)
        // BUT ONLY IF IT IS NOT STALE (RFC-0029 Pillar 6: Forensic Purity)
        let last_val = {
            let last = LAST_RESULT.lock();
            if let Some((val, ts)) = &*last {
                // Check if file has been modified since the result was generated
                let mtime = std::fs::metadata(&target)
                    .and_then(|m| m.modified())
                    .unwrap_or(SystemTime::UNIX_EPOCH);

                if mtime <= *ts {
                    Some(val.clone())
                } else {
                    log::debug!("Suppressing stale vibe cache (mtime > ts)");
                    None
                }
            } else {
                None
            }
        };

        if let Some(val) = last_val
            && let Ok(json_str) = serde_json::to_string(&val)
        {
            let _ = ws_stream.send(Message::Text(json_str)).await;
        }

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
