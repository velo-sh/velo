//! Unit tests for Zygote IPC (Unix Socket communication)
//!
//! TDD: These tests verify MessagePack protocol with length-prefix framing.

#[cfg(unix)]
mod ipc_tests {
    use std::io::{Read, Write};
    use std::path::PathBuf;
    use std::time::Duration;

    /// Test socket path generation
    #[test]
    fn test_socket_path_generation() {
        // Socket should be in temp directory with unique name
        let socket_path = velo::zygote::ipc::default_socket_path();
        assert!(socket_path.to_string_lossy().contains("velo-zygote"));
    }

    /// Test basic socket creation and cleanup
    #[test]
    fn test_socket_create_and_cleanup() {
        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-zygote.sock");

        // Create socket
        let listener = velo::zygote::ipc::create_listener(&socket_path).unwrap();
        assert!(socket_path.exists());

        // Cleanup
        drop(listener);
        velo::zygote::ipc::cleanup_socket(&socket_path);
        assert!(!socket_path.exists());
    }

    /// Test message serialization/deserialization with MessagePack
    #[test]
    fn test_message_roundtrip() {
        use velo::zygote::ipc::{ZygoteCommand, ZygoteResponse};

        // Test FORK command with MessagePack
        let fork_cmd = ZygoteCommand::Fork {
            script_path: PathBuf::from("/tmp/test.py"),
            args: vec!["--arg1".to_string()],
            stdout_path: None,
            stderr_path: None,
            exit_code_path: None,
            async_mode: false,
            fast_mode: false,
            bundle_path: None,
            project_root: None,
            max_bundle_size: None,
            env: Box::new(std::collections::HashMap::new()),
            shm_size: None,
            request_id: Some("test-fork-msgpack".to_string()),
        };
        let serialized = rmp_serde::to_vec(&fork_cmd).unwrap();
        let deserialized: ZygoteCommand = rmp_serde::from_slice(&serialized).unwrap();
        assert!(matches!(deserialized, ZygoteCommand::Fork { .. }));

        // Test READY response with MessagePack
        let ready_resp = ZygoteResponse::Ready;
        let serialized = rmp_serde::to_vec(&ready_resp).unwrap();
        let deserialized: ZygoteResponse = rmp_serde::from_slice(&serialized).unwrap();
        assert!(matches!(deserialized, ZygoteResponse::Ready));

        // Test FORKED response with MessagePack
        let forked_resp = ZygoteResponse::Forked {
            worker_pid: 12345,
            exit_code: None,
        };
        let serialized = rmp_serde::to_vec(&forked_resp).unwrap();
        let deserialized: ZygoteResponse = rmp_serde::from_slice(&serialized).unwrap();
        assert!(matches!(
            deserialized,
            ZygoteResponse::Forked {
                worker_pid: 12345,
                ..
            }
        ));
    }

    /// Protocol version for testing
    const PROTOCOL_VERSION: u8 = 0x01;

    /// Helper: Send MessagePack message with length prefix and version byte
    fn send_msgpack<T: serde::Serialize>(stream: &mut std::os::unix::net::UnixStream, msg: &T) {
        let payload = rmp_serde::to_vec(msg).unwrap();
        let total_len = 1 + payload.len(); // version + payload
        let len_bytes = (total_len as u32).to_le_bytes();
        stream.write_all(&len_bytes).unwrap();
        stream.write_all(&[PROTOCOL_VERSION]).unwrap(); // version byte
        stream.write_all(&payload).unwrap();
        stream.flush().unwrap();
    }

    /// Helper: Receive MessagePack message with length prefix and version byte
    fn recv_msgpack<T: serde::de::DeserializeOwned>(
        stream: &mut std::os::unix::net::UnixStream,
    ) -> T {
        let mut len_buf = [0u8; 4];
        stream.read_exact(&mut len_buf).unwrap();
        let total_len = u32::from_le_bytes(len_buf) as usize;

        // Read version byte
        let mut version_buf = [0u8; 1];
        stream.read_exact(&mut version_buf).unwrap();
        assert_eq!(
            version_buf[0], PROTOCOL_VERSION,
            "Protocol version mismatch"
        );

        // Read payload
        let payload_len = total_len - 1;
        let mut buf = vec![0u8; payload_len];
        stream.read_exact(&mut buf).unwrap();
        rmp_serde::from_slice(&buf).unwrap()
    }

    /// Test socket roundtrip communication with MessagePack protocol
    #[test]
    fn test_socket_roundtrip() {
        use std::thread;
        use velo::zygote::ipc::{ZygoteCommand, ZygoteResponse};

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-roundtrip.sock");
        let socket_path_clone = socket_path.clone();

        // Start server in background thread (mock Zygote with MessagePack)
        let server_handle = thread::spawn(move || {
            let listener = velo::zygote::ipc::create_listener(&socket_path_clone).unwrap();

            // Accept connection
            let (mut stream, _) = listener.accept().unwrap();

            // Send READY first (per protocol) using MessagePack
            send_msgpack(&mut stream, &ZygoteResponse::Ready);

            // Read command using MessagePack
            let cmd: ZygoteCommand = recv_msgpack(&mut stream);

            // Verify we got FORK command
            assert!(matches!(cmd, ZygoteCommand::Fork { .. }));

            // Send FORKED response using MessagePack
            send_msgpack(
                &mut stream,
                &ZygoteResponse::Forked {
                    worker_pid: 42,
                    exit_code: None,
                },
            );
        });

        // Give server time to start
        thread::sleep(Duration::from_millis(100));

        // Connect as client and send command
        let response = velo::zygote::ipc::send_command(
            &socket_path,
            ZygoteCommand::Fork {
                script_path: PathBuf::from("/tmp/test.py"),
                args: vec![],
                stdout_path: None,
                stderr_path: None,
                exit_code_path: None,
                async_mode: false,
                fast_mode: false,
                bundle_path: None,
                project_root: None,
                max_bundle_size: None,
                env: Box::new(std::collections::HashMap::new()),
                shm_size: None,
                request_id: Some("test-roundtrip".to_string()),
            },
            None,
        )
        .unwrap();

        // Verify response
        assert!(matches!(
            response,
            ZygoteResponse::Forked { worker_pid: 42, .. }
        ));

        server_handle.join().unwrap();
    }

    /// Test socket timeout handling
    #[test]
    fn test_socket_timeout() {
        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("nonexistent.sock");

        // Connecting to non-existent socket should fail
        let result = velo::zygote::ipc::send_command(
            &socket_path,
            velo::zygote::ipc::ZygoteCommand::Shutdown,
            None,
        );
        assert!(result.is_err());
    }
}

/// Windows fallback test
#[cfg(windows)]
mod windows_tests {
    #[test]
    fn test_zygote_not_supported_on_windows() {
        // Zygote should gracefully indicate unsupported on Windows
        assert!(velo::zygote::is_supported() == false);
    }
}
