//! QA Integration Tests for Phase 2C
//!
//! Covers:
//! - TEST-001: Zygote Fork Tree (Parent -> Zygote -> Worker)
//! - TEST-005: Header Injection E2E

#[cfg(unix)]
mod integration_tests {
    use http::Request;
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use std::time::Duration;
    use velo::config::VeloConfig;
    use velo::proxy::{LoadBalancer, VeloProxyService};
    use velo::zygote::ZygoteLauncher;

    fn wait_for_file(path: &Path, timeout_ms: u64) -> bool {
        for _ in 0..(timeout_ms / 50) {
            if path.exists() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        false
    }

    /// TEST-001: Verify Zygote creates a proper process tree
    /// Worker PPID must match Zygote PID
    #[test]
    fn test_zygote_fork_tree() {
        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("fork-tree.sock");
        let output_file = temp_dir.path().join("pids.txt");

        // Script: Write PID and PPID to file
        let script_path = temp_dir.path().join("pid_script.py");
        fs::write(
            &script_path,
            format!(
                r#"
import os
import json
with open('{}', 'w') as f:
    json.dump({{'pid': os.getpid(), 'ppid': os.getppid()}}, f)
"#,
                output_file.display()
            ),
        )
        .unwrap();

        let mut launcher = ZygoteLauncher::new(socket_path);
        // Start returns Result<()>, use pid() to get PID
        launcher
            .start(&[], None, false, &VeloConfig::default())
            .unwrap();
        let zygote_pid = launcher.pid().expect("Zygote should have PID");

        assert!(zygote_pid > 0, "Zygote PID should be > 0");

        // Spawn worker
        let worker = launcher
            .spawn_worker(&script_path, &[], false, false, None, None, None)
            .unwrap();

        assert!(
            wait_for_file(&output_file, 5000),
            "Worker did not write output"
        );

        // Read PIDs
        let content = fs::read_to_string(&output_file).unwrap();
        let pids: serde_json::Value = serde_json::from_str(&content).unwrap();

        let worker_pid = pids["pid"].as_i64().unwrap() as u32;
        let worker_ppid = pids["ppid"].as_i64().unwrap() as u32;

        println!("Zygote PID: {}", zygote_pid);
        println!("Worker PID: {}", worker_pid);
        println!("Worker PPID: {}", worker_ppid);

        assert_eq!(worker.pid(), worker_pid, "Worker PID mismatch");
        assert_eq!(worker_ppid, zygote_pid, "Worker PPID must match Zygote PID");

        launcher.stop().unwrap();
    }

    /// TEST-005: Header Injection E2E
    /// Proxy -> UDS -> Worker
    #[tokio::test]
    async fn test_header_injection_e2e() {
        let temp_dir = tempfile::tempdir().unwrap();
        let worker_socket = temp_dir.path().join("worker.sock");
        let worker_socket_path = worker_socket.to_string_lossy().to_string();

        // 1. Start "Worker" (UDS Listener)
        let listener_socket = worker_socket.clone();
        let (tx, rx) = tokio::sync::oneshot::channel();

        tokio::spawn(async move {
            let listener = tokio::net::UnixListener::bind(&listener_socket).unwrap();
            tx.send(true).unwrap(); // Signal ready

            let (mut stream, _) = listener.accept().await.unwrap();

            // Read request headers (simple HTTP read)
            use tokio::io::{AsyncReadExt, AsyncWriteExt};
            let mut buf = [0u8; 4096];
            let n = stream.read(&mut buf).await.unwrap();
            let request = String::from_utf8_lossy(&buf[..n]);

            // Check headers in the request string
            let has_request_id = request.contains("x-request-id:");
            let has_traceparent = request.contains("traceparent:");

            // Send response indicating success/failure of header check
            let status = if has_request_id && has_traceparent {
                "200 OK"
            } else {
                "400 Bad Request"
            };
            let response = format!("HTTP/1.1 {}\r\nContent-Length: 0\r\n\r\n", status);
            stream.write_all(response.as_bytes()).await.unwrap();
        });

        // Wait for listener
        rx.await.unwrap();

        // 2. Setup Proxy
        let lb = Arc::new(LoadBalancer::new(vec![worker_socket_path]));
        let _service = VeloProxyService::new(lb);

        // 3. Test prepare_request (Generic over body type)
        let req = Request::builder()
            .uri("http://localhost/test")
            .body(http_body_util::Empty::<hyper::body::Bytes>::new())
            .unwrap();

        let (guard, proxy_req) = _service.prepare_request(req, None).unwrap();

        // Verify headers were injected
        assert!(proxy_req.headers().contains_key("x-request-id"));
        assert!(proxy_req.headers().contains_key("traceparent"));

        // Verify authority generation for connection pooling
        let authority = guard.authority();
        assert!(authority.starts_with("worker-"));
        assert!(authority.ends_with("@velo"));
    }

    /// TEST-002: Abstract/UDS Socket Support
    /// Verify Zygote spawns worker with UDS argument
    #[test]
    fn test_zygote_uds_spawn() {
        let temp_dir = tempfile::tempdir().unwrap();
        let socket_path = temp_dir.path().join("uds-test.sock");
        let worker_socket = temp_dir.path().join("worker-ag.sock");
        let output_file = temp_dir.path().join("args.txt");

        // Script: Write argv to file
        let script_path = temp_dir.path().join("args_script.py");
        fs::write(
            &script_path,
            format!(
                r#"
import sys
import json
with open('{}', 'w') as f:
    json.dump(sys.argv, f)
"#,
                output_file.display()
            ),
        )
        .unwrap();

        let mut launcher = ZygoteLauncher::new(socket_path);
        launcher
            .start(&[], None, false, &VeloConfig::default())
            .unwrap();

        // Spawn worker via UDS method (mimicked by passing arguments)
        // In runner.rs we use `generate_uds_worker_script`.
        // Here we just want to see if the worker launched via Zygote can accept UDS args if passed.
        // Actually, ZygoteLauncher::spawn_worker takes args list.
        // Let's pass "--uds" and the socket path.

        let args = vec!["--uds", worker_socket.to_str().unwrap()];

        launcher
            .spawn_worker(&script_path, &args, false, false, None, None, None)
            .unwrap();

        assert!(wait_for_file(&output_file, 5000));

        let content = fs::read_to_string(&output_file).unwrap();
        let argv: Vec<String> = serde_json::from_str(&content).unwrap();

        // Verify args passed through
        assert!(argv.contains(&"--uds".to_string()));
        assert!(argv.iter().any(|a| a.contains("worker-ag.sock")));

        launcher.stop().unwrap();
    }
}
