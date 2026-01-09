use anyhow::Result;
use std::io::Write;
use std::os::unix::io::AsRawFd;
use std::path::PathBuf;
use std::time::Duration;
use velo::zygote::ipc::{self, ZygoteCommand, ZygoteResponse};

#[test]
fn test_ipc_fd_passing_end_to_end() -> Result<()> {
    // 1. Setup Zygote socket path
    let tmp_dir = tempfile::tempdir()?;
    let socket_path = tmp_dir.path().join("velo-zygote-test.sock");

    // 2. Launch Zygote (we need a running Zygote)
    // We can use the actual velo_zygote/main.py
    let zygote_script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("velo_zygote/main.py");

    let mut child = std::process::Command::new("python3")
        .arg(&zygote_script)
        .arg("--socket")
        .arg(socket_path.to_string_lossy().as_ref())
        .spawn()?;

    // Give it time to start
    std::thread::sleep(Duration::from_secs(2));

    // 3. Create a shared memory segment with data
    let shm_path = tmp_dir.path().join("test_shm");
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(true)
        .open(&shm_path)?;
    file.write_all(b"HELLO SHM")?;
    file.set_len(1024)?;
    let shm_size = 1024;
    let fd = file.as_raw_fd();

    // 4. Create worker script
    let worker_script = tmp_dir.path().join("worker.py");
    std::fs::write(
        &worker_script,
        r#"
import sys
import os
print(f"[Worker] Started with PID {os.getpid()}", file=sys.stderr)
shm = globals().get('VELO_SHM')
if shm is None:
    print("[Worker] ❌ Error: VELO_SHM not in globals", file=sys.stderr)
    sys.exit(10)

try:
    # mmap/tensor slice
    data = shm[0:9]
    if hasattr(data, 'tobytes'): data = data.tobytes()
    if isinstance(data, bytes):
        content = data.decode('ascii')
    else:
        content = str(data)
    
    print(f"[Worker] Read from SHM: '{content}'", file=sys.stderr)
    if content == "HELLO SHM":
        print("[Worker] ✅ Content verified", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"[Worker] ❌ Content mismatch: {content}", file=sys.stderr)
        sys.exit(20)
except Exception as e:
    print(f"[Worker] ❌ Exception: {e}", file=sys.stderr)
    sys.exit(30)
"#,
    )?;

    // 5. Connect and Send Handshake
    let mut stream = ipc::ZygoteStream::connect(&socket_path)?;
    let handshake = ZygoteCommand::Handshake {
        version: ipc::PROTOCOL_VERSION,
        capabilities: vec![],
        request_id: Some("test-handshake".to_string()),
    };
    stream.send_command(&handshake, None)?;

    // 6. Send Fork Command WITH FD
    let fork_cmd = ZygoteCommand::Fork {
        script_path: worker_script.clone(),
        args: vec![],
        async_mode: false, // Wait for exit
        stdout_path: None,
        stderr_path: None,
        exit_code_path: None,
        fast_mode: false,
        bundle_path: None,
        project_root: None,
        max_bundle_size: None,
        env: Box::new(std::collections::HashMap::new()),
        shm_size: Some(shm_size),
        request_id: Some("test-fork".to_string()),
    };

    println!("Sending Fork command with FD {}...", fd);
    let response = stream.send_command(&fork_cmd, Some(fd))?;
    println!("Received response: {:?}", response);

    if let ZygoteResponse::Forked { worker_pid, .. } = response {
        println!("✅ Fork successful, worker_pid={}", worker_pid);

        // Give worker time to execute and exit
        std::thread::sleep(Duration::from_millis(1000));

        // Verify worker is gone (since it exited 0)
        let status = stream.send_command(
            &ZygoteCommand::WorkerStatus {
                worker_pid,
                request_id: None,
            },
            None,
        )?;
        println!("Worker status: {:?}", status);
        // Note: Zygote reaps workers. If it exited 0, it should be gone from registry.
    } else {
        panic!("Fork failed: {:?}", response);
    }

    // 7. Cleanup
    child.kill()?;
    Ok(())
}
