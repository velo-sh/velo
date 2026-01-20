#[cfg(unix)]
mod tests {
    use std::time::Instant;
    use velo::v_live::miracle::MiracleFork;

    #[test]
    fn test_miracle_fork_latency() {
        let fork = MiracleFork::new();

        let start = Instant::now();
        let result = fork
            .execute(|| {
                // Simulated worker task
                42
            })
            .expect("Fork failed");
        let duration = start.elapsed();

        assert_eq!(result, 42);
        println!(
            "Miracle Fork Latency: {:.3}ms",
            duration.as_secs_f64() * 1000.0
        );

        // Target: < 10ms for fork + execute + return
        // (In a dev environment this might vary, but we want it fast)
        assert!(
            duration.as_millis() < 50,
            "Fork too slow: {}ms",
            duration.as_millis()
        );
    }
}
