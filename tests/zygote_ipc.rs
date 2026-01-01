//! Unit tests for Zygote IPC (Unix Socket communication)
//!
//! TDD: These tests are written FIRST, before implementation.

#[cfg(unix)]
mod ipc_tests {
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

    /// Test message serialization/deserialization
    #[test]
    fn test_message_roundtrip() {
        use velo::zygote::ipc::{ZygoteCommand, ZygoteResponse};

        // Test FORK command
        let fork_cmd = ZygoteCommand::Fork {
            script_path: PathBuf::from("/tmp/test.py"),
            args: vec!["--arg1".to_string()],
        };
        let serialized = serde_json::to_string(&fork_cmd).unwrap();
        let deserialized: ZygoteCommand = serde_json::from_str(&serialized).unwrap();
        assert!(matches!(deserialized, ZygoteCommand::Fork { .. }));

        // Test READY response
        let ready_resp = ZygoteResponse::Ready;
        let serialized = serde_json::to_string(&ready_resp).unwrap();
        let deserialized: ZygoteResponse = serde_json::from_str(&serialized).unwrap();
        assert!(matches!(deserialized, ZygoteResponse::Ready));

        // Test FORKED response
        let forked_resp = ZygoteResponse::Forked { worker_pid: 12345 };
        let serialized = serde_json::to_string(&forked_resp).unwrap();
        let deserialized: ZygoteResponse = serde_json::from_str(&serialized).unwrap();
        assert!(matches!(
            deserialized,
            ZygoteResponse::Forked { worker_pid: 12345 }
        ));
    }

    /// Test socket roundtrip communication
    #[test]
    fn test_socket_roundtrip() {
        use std::io::{BufRead, BufReader, Write};
        use std::thread;
        use velo::zygote::ipc::{ZygoteCommand, ZygoteResponse};

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-roundtrip.sock");
        let socket_path_clone = socket_path.clone();

        // Start server in background thread
        let server_handle = thread::spawn(move || {
            let listener = velo::zygote::ipc::create_listener(&socket_path_clone).unwrap();

            // Accept connection
            let (stream, _) = listener.accept().unwrap();
            let mut stream_write = stream.try_clone().unwrap();
            let mut reader = BufReader::new(stream);

            // Send READY first (per protocol)
            let ready = serde_json::to_string(&ZygoteResponse::Ready).unwrap();
            writeln!(stream_write, "{}", ready).unwrap();

            // Read command
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            let cmd: ZygoteCommand = serde_json::from_str(&line).unwrap();

            // Verify we got FORK command
            assert!(matches!(cmd, ZygoteCommand::Fork { .. }));

            // Send FORKED response
            let resp = serde_json::to_string(&ZygoteResponse::Forked { worker_pid: 42 }).unwrap();
            writeln!(stream_write, "{}", resp).unwrap();
        });

        // Give server time to start
        thread::sleep(Duration::from_millis(100));

        // Connect as client and send command
        let response = velo::zygote::ipc::send_command(
            &socket_path,
            ZygoteCommand::Fork {
                script_path: PathBuf::from("/tmp/test.py"),
                args: vec![],
            },
        )
        .unwrap();

        // Verify response
        assert!(matches!(
            response,
            ZygoteResponse::Forked { worker_pid: 42 }
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
