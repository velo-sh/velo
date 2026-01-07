use anyhow::Result;
use std::fs::File;
use std::os::unix::io::{AsRawFd, RawFd};
use std::path::{Path, PathBuf};
use std::time::Duration;
use velo::shm::registry::MemoryRegistry;
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

    // 3. Create a dummy shared memory segment
    let registry = MemoryRegistry::new();
    // Create a dummy tensor file
    let tensor_path = tmp_dir.path().join("model.safetensors");
    // Write minimal valid safetensors (8 bytes len + empty json + padding)
    // Actually, create_segment checks for header len.
    // Let's just create a dummy file > 8 bytes.
    std::fs::write(&tensor_path, vec![0u8; 100])?;

    // We expect create_segment to fail validation if it's not valid safetensors (H-29),
    // but we just want an FD.
    // Actually, let's skip MemoryRegistry validation failure by just creating a raw memfd/file manually
    // if create_segment is too strict.
    // BUT, we want to test MemoryRegistry too?
    // Let's just create a raw File for this test to isolate IPC testing.
    let file = File::create(tmp_dir.path().join("test_shm"))?;
    file.set_len(1024)?;

    let fd = file.as_raw_fd();
    let shm_size = 1024;

    // 4. Connect and Send Handshake
    let mut stream = ipc::ZygoteStream::connect(&socket_path)?;

    let handshake = ZygoteCommand::Handshake {
        version: ipc::PROTOCOL_VERSION,
        capabilities: vec![],
    };
    stream.send_command(&handshake, None)?;

    // 5. Send Fork Command WITH FD
    let fork_cmd = ZygoteCommand::Fork {
        script_path: PathBuf::from("/tmp/worker.py"), // Dummy
        args: vec![],
        async_mode: true,
        stdout_path: None,
        stderr_path: None,
        exit_code_path: None,
        fast_mode: false,
        bundle_path: None,
        project_root: None,
        max_bundle_size: None,
        shm_size: Some(shm_size),
    };

    println!("Sending Fork command with FD {}...", fd);
    // Send with the FD
    let response = stream.send_command(&fork_cmd, Some(fd))?;

    println!("Received response: {:?}", response);

    match response {
        ZygoteResponse::Forked { .. } => println!("✅ Fork successful"),
        ZygoteResponse::Error { message } => {
            // It might fail to fork because script doesn't exist, but that's fine.
            // We want to verify the NETWORK layer didn't crash.
            println!("⚠️ Fork failed (expected): {}", message);
        }
        _ => panic!("Unexpected response: {:?}", response),
    }

    // 6. Cleanup
    child.kill()?;

    Ok(())
}
