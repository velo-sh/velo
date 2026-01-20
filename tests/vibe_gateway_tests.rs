use futures_util::StreamExt;
use std::time::Duration;
use tokio::time::timeout;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use velo::v_live::gateway::VibeGateway;

#[tokio::test]
async fn test_gateway_broadcasts_json() {
    // 1. Start Gateway in background
    let addr = "127.0.0.1:9999";
    let gateway = VibeGateway::new(addr, "test.py".into());
    let _rx = gateway.subscribe();

    let server_handle = tokio::spawn(async move {
        gateway.run().await.unwrap();
    });

    // Wait for server to start
    tokio::time::sleep(Duration::from_millis(200)).await;

    // 2. Connect client
    let url = format!("ws://{}", addr);
    let (mut ws_stream, _) = connect_async(url).await.expect("Failed to connect");

    // 3. Broadcast message
    let test_msg = serde_json::json!({"status": "ok", "payload": "test"});
    VibeGateway::broadcast_sync(test_msg.clone());

    // 4. Verify client received JSON
    let msg = timeout(Duration::from_secs(1), ws_stream.next())
        .await
        .expect("Timeout waiting for message")
        .expect("No message received")
        .expect("WS error");

    match msg {
        Message::Text(text) => {
            let received: serde_json::Value =
                serde_json::from_str(&text).expect("Invalid JSON received");
            assert_eq!(received["payload"], "test");
        }
        _ => panic!("Expected text message, got {:?}", msg),
    }

    server_handle.abort();
}
