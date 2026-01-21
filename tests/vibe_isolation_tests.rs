use std::os::unix::net::UnixListener;
use tempfile::tempdir;
use velo::v_live::isolation::PipeFence;

#[test]
fn test_pipe_fence_ensures_atomic_binding() {
    let dir = tempdir().unwrap();
    let socket_path = dir.path().join("vibe.sock");

    // 1. Create an initial "stale" socket
    {
        let _listener = UnixListener::bind(&socket_path).unwrap();
        // Socket exists now
    }

    // 2. Use PipeFence to clear and bind new
    let fence = PipeFence::new(&socket_path);
    let _new_listener = fence
        .bind()
        .expect("PipeFence should have cleared the path and bound successfully");

    // 3. Verify that the path is now owned by us
    assert!(socket_path.exists());
}

#[test]
fn test_pipe_fence_drains_stale_data() {
    // This is harder to test without a full client-server setup,
    // but we can at least test the "cleanup" phase.
    let dir = tempdir().unwrap();
    let socket_path = dir.path().join("vibe.sock");

    let fence = PipeFence::new(&socket_path);
    fence
        .cleanup()
        .expect("Cleanup should work even on non-existent path");

    assert!(!socket_path.exists());
}
