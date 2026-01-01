//! Unit tests for Zygote basic functionality
//!
//! TDD: These tests are written FIRST, before implementation.

#[cfg(unix)]
mod basic_tests {
    use std::path::PathBuf;

    /// Test Zygote start command creates a running Zygote process
    #[test]
    fn test_zygote_start() {
        use velo::zygote::ZygoteLauncher;

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-zygote.sock");

        let mut launcher = ZygoteLauncher::new(socket_path.clone());

        // Start should succeed
        let result = launcher.start(&[]);
        assert!(result.is_ok(), "Zygote should start successfully");

        // Zygote should be running
        assert!(launcher.is_running());

        // Cleanup
        launcher.stop().unwrap();
        assert!(!launcher.is_running());
    }

    /// Test Zygote stop command gracefully shuts down Zygote
    #[test]
    fn test_zygote_stop() {
        use velo::zygote::ZygoteLauncher;

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-zygote-stop.sock");

        let mut launcher = ZygoteLauncher::new(socket_path.clone());
        launcher.start(&[]).unwrap();

        // Stop should succeed
        let result = launcher.stop();
        assert!(result.is_ok(), "Zygote should stop gracefully");

        // Socket should be cleaned up
        assert!(!socket_path.exists());
    }

    /// Test --zygote flag is properly parsed
    #[test]
    fn test_zygote_flag_parsed() {
        use velo::zygote::cli::parse_zygote_args;

        // With --zygote flag
        let args = vec!["velo", "run", "--zygote", "script.py"];
        let parsed = parse_zygote_args(&args);
        assert!(parsed.zygote_enabled);
        assert_eq!(parsed.script_path, Some(PathBuf::from("script.py")));

        // Without --zygote flag
        let args = vec!["velo", "run", "script.py"];
        let parsed = parse_zygote_args(&args);
        assert!(!parsed.zygote_enabled);
    }

    /// Test error messages are clear
    #[test]
    fn test_zygote_error_messages() {
        use velo::zygote::error::ZygoteError;

        // Socket connection error
        let err = ZygoteError::ConnectionFailed("test".to_string());
        let msg = err.to_string();
        assert!(msg.contains("connection") || msg.contains("Connection"));

        // Fork error
        let err = ZygoteError::ForkFailed("test".to_string());
        let msg = err.to_string();
        assert!(msg.contains("fork") || msg.contains("Fork"));
    }

    /// Test Zygote status output
    #[test]
    fn test_status_output() {
        use velo::zygote::ZygoteLauncher;

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("test-status.sock");

        let mut launcher = ZygoteLauncher::new(socket_path);

        // Status when not running
        let status = launcher.status();
        assert!(status.contains("not running") || status.contains("Not running"));

        // Status when running
        launcher.start(&[]).unwrap();
        let status = launcher.status();
        assert!(status.contains("running") || status.contains("Running"));
        assert!(status.contains("PID") || status.contains("pid"));

        launcher.stop().unwrap();
    }
}

/// Test Zygote spawn worker functionality
#[cfg(unix)]
mod spawn_tests {
    /// Test spawning a worker that executes a script
    #[test]
    fn test_spawn_worker_executes_script() {
        use std::fs;
        use velo::zygote::ZygoteLauncher;

        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("spawn-test.sock");
        let output_file = temp_dir.path().join("output.txt");

        // Create a simple test script
        let script_path = temp_dir.path().join("test_script.py");
        fs::write(
            &script_path,
            format!(
                "with open('{}', 'w') as f: f.write('hello from worker')",
                output_file.display()
            ),
        )
        .unwrap();

        let mut launcher = ZygoteLauncher::new(socket_path);
        launcher.start(&[]).unwrap();

        // Spawn worker
        let worker = launcher.spawn_worker(&script_path, &[]).unwrap();
        assert!(worker.pid() > 0);

        // Wait for output file to be created (worker runs in Python Zygote, not our process)
        for _ in 0..50 {
            if output_file.exists() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }

        // Verify script executed
        assert!(
            output_file.exists(),
            "Output file should be created by worker"
        );
        let content = fs::read_to_string(&output_file).unwrap();
        assert_eq!(content, "hello from worker");

        launcher.stop().unwrap();
    }
}
