#[cfg(unix)]
#[cfg(test)]
mod tests {
    use std::process::{Command, Stdio};
    use std::thread;
    use std::time::Duration;
    use velo::v_live::reaper::reap_zombies;

    #[test]
    fn test_greedy_reaper_cleans_multiple_zombies() {
        // 1. Create multiple zombie processes
        // By spawning processes that exit immediately
        let mut children = Vec::new();
        for _ in 0..5 {
            let child = Command::new("true")
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("Failed to spawn dummy child");
            children.push(child);
        }

        // Wait a bit to ensure they have exited and become zombies
        thread::sleep(Duration::from_millis(100));

        // 2. Run the greedy reaper
        let reaped_count = reap_zombies();

        // 3. Assert that at least 5 processes were reaped
        // (Note: there might be other orphans on the system,
        // but we expect at least ours)
        assert!(
            reaped_count >= 5,
            "Reaper should have cleaned at least 5 zombies, got {}",
            reaped_count
        );
    }
}
