//! Load Balancer - Least Connections strategy for UDS workers
//!
//! RFC-0011 B.2.2: Implements least-connections load balancing across workers.
//!
//! ## Algorithm
//!
//! Selects the worker with the fewest active connections. Uses atomic counters
//! for thread-safety without locks.

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use tokio::net::UnixStream;

/// Represents a single worker node in the load balancer.
#[derive(Debug)]
pub struct WorkerNode {
    /// Path to the worker's Unix socket (protected by RwLock for respawns).
    socket_path: std::sync::RwLock<String>,
    /// Unique worker ID for connection pooling authority.
    pub worker_id: u64,
    /// Worker process PID for Gate H peer authentication (DEF-72-H01).
    worker_pid: std::sync::atomic::AtomicU32,
    /// Number of active connections to this worker.
    active_connections: AtomicUsize,
    /// Consecutive failures for circuit breaker.
    consecutive_failures: AtomicUsize,
    /// Whether this worker is healthy.
    healthy: std::sync::atomic::AtomicBool,
}

impl WorkerNode {
    /// Create a new worker node.
    pub fn new(socket_path: String, worker_id: u64) -> Self {
        Self::with_pid(socket_path, worker_id, 0)
    }

    /// Create a new worker node with a known PID (Gate H compliance).
    pub fn with_pid(socket_path: String, worker_id: u64, pid: u32) -> Self {
        eprintln!(
            "[LB] Created worker node {} at {} with pid {}",
            worker_id, socket_path, pid
        );
        Self {
            socket_path: std::sync::RwLock::new(socket_path),
            worker_id,
            worker_pid: std::sync::atomic::AtomicU32::new(pid),
            active_connections: AtomicUsize::new(0),
            consecutive_failures: AtomicUsize::new(0),
            // STB-SOCKET-RACE: Start workers as unhealthy until socket is verified
            // This prevents the race condition where health check runs before socket creation
            healthy: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// Get the current socket path for this worker.
    pub fn socket_path(&self) -> String {
        self.socket_path
            .read()
            .expect("Poisoned socket_path lock")
            .clone()
    }

    /// Update the socket path (called during worker respawn).
    pub fn update_path(&self, new_path: String) {
        if let Ok(mut guard) = self.socket_path.write() {
            *guard = new_path;
        }
    }

    /// Get the worker ID.
    pub fn id(&self) -> u64 {
        self.worker_id
    }

    /// Get the worker PID (Gate H: for peer authentication).
    pub fn pid(&self) -> u32 {
        self.worker_pid.load(Ordering::Relaxed)
    }

    /// Update the worker PID (called during respawn).
    pub fn update_pid(&self, new_pid: u32) {
        self.worker_pid.store(new_pid, Ordering::Relaxed);
    }

    /// Get the current number of active connections.
    pub fn active_connections(&self) -> usize {
        self.active_connections.load(Ordering::Relaxed)
    }

    /// Increment active connections (called when starting a request).
    pub fn increment(&self) {
        self.active_connections.fetch_add(1, Ordering::Relaxed);
    }

    /// Decrement active connections (called when request completes).
    pub fn decrement(&self) {
        // Saturating sub to avoid underflow
        let prev = self.active_connections.fetch_sub(1, Ordering::Relaxed);
        if prev == 0 {
            // This shouldn't happen, but protect against underflow
            self.active_connections.store(0, Ordering::Relaxed);
        }
    }

    /// Check if this worker is healthy.
    pub fn is_healthy(&self) -> bool {
        self.healthy.load(Ordering::Relaxed)
    }

    /// Mark this worker as unhealthy.
    pub fn mark_unhealthy(&self) {
        eprintln!("[LB] Worker marked UNHEALTHY (circuit breaker tripped)");
        self.healthy.store(false, Ordering::Relaxed);
    }

    /// Mark this worker as healthy.
    pub fn mark_healthy(&self) {
        self.healthy.store(true, Ordering::Relaxed);
        self.consecutive_failures.store(0, Ordering::Relaxed);
    }

    /// Record a failure for circuit breaking.
    pub fn record_failure(&self) {
        let failures = self.consecutive_failures.fetch_add(1, Ordering::Relaxed) + 1;
        // RFC-0011 Phase 3C: Circuit Breaker Threshold
        if failures >= 5 {
            self.mark_unhealthy();
        }
    }

    /// Record a success to reset circuit breaker.
    pub fn record_success(&self) {
        self.consecutive_failures.store(0, Ordering::Relaxed);
    }
}

/// RAII guard that decrements connection count when dropped.
///
/// RFC-0011 B.4: Connection tracking uses RAII for accurate counting.
pub struct ConnectionGuard {
    worker: Arc<WorkerNode>,
}

impl ConnectionGuard {
    /// Create a new connection guard for the given worker.
    pub fn new(worker: Arc<WorkerNode>) -> Self {
        worker.increment();
        Self { worker }
    }

    /// Get the socket path for this connection.
    pub fn socket_path(&self) -> String {
        self.worker.socket_path()
    }

    /// Get the worker ID.
    pub fn worker_id(&self) -> u64 {
        self.worker.worker_id
    }

    /// Generate unique URI authority for this worker.
    pub fn authority(&self) -> String {
        format!("worker-{}@velo", self.worker.worker_id)
    }

    /// Record a successful request.
    pub fn record_success(&self) {
        self.worker.record_success();
    }

    /// Record a failed request.
    pub fn record_failure(&self) {
        self.worker.record_failure();
    }
}

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.worker.decrement();
    }
}

/// Load balancer for distributing requests across UDS workers.
///
/// RFC-0011 B.2.2: Uses least-connections strategy with round-robin tie-breaker.
#[derive(Debug)]
pub struct LoadBalancer {
    workers: Vec<Arc<WorkerNode>>,
    /// Round-robin counter for tie-breaking when connections are equal
    round_robin_counter: AtomicUsize,
}

impl Clone for LoadBalancer {
    fn clone(&self) -> Self {
        Self {
            workers: self.workers.clone(),
            round_robin_counter: AtomicUsize::new(self.round_robin_counter.load(Ordering::Relaxed)),
        }
    }
}

impl LoadBalancer {
    /// Create a new load balancer with the given workers.
    /// IDs are assigned sequentially starting from 0.
    pub fn new(socket_paths: Vec<String>) -> Self {
        let workers = socket_paths
            .into_iter()
            .enumerate()
            .map(|(id, path)| Arc::new(WorkerNode::new(path, id as u64)))
            .collect();
        Self {
            workers,
            round_robin_counter: AtomicUsize::new(0),
        }
    }

    /// Select a worker using least-connections strategy with round-robin tie-breaker.
    ///
    /// RFC-0011 §6A.7: When connections are equal (common for quick requests),
    /// use round-robin to ensure fair distribution across workers.
    ///
    /// Returns a ConnectionGuard that automatically tracks the connection.
    /// Returns None if no healthy workers are available.
    pub fn select_worker(&self) -> Option<ConnectionGuard> {
        let healthy: Vec<_> = self.workers.iter().filter(|w| w.is_healthy()).collect();

        if healthy.is_empty() {
            let statuses: Vec<String> = self
                .workers
                .iter()
                .map(|w| format!("{}:{}", w.socket_path(), w.is_healthy()))
                .collect();
            eprintln!(
                "[LB] No healthy workers available among {} total. Statuses: {:?}",
                self.workers.len(),
                statuses
            );
            return None;
        }

        // Find minimum active connections
        let min_connections = healthy
            .iter()
            .map(|w| w.active_connections())
            .min()
            .unwrap_or(0);

        // Get all workers with minimum connections (tie candidates)
        let candidates: Vec<_> = healthy
            .iter()
            .filter(|w| w.active_connections() == min_connections)
            .collect();

        // Use round-robin to select among candidates with equal connections
        let rr_index = self.round_robin_counter.fetch_add(1, Ordering::Relaxed);

        let selected = if !candidates.is_empty() {
            candidates[rr_index % candidates.len()]
        } else {
            healthy[rr_index % healthy.len()]
        };

        eprintln!(
            "[LB] selected={} connections={} candidates={} healthy={} rr_index={}",
            selected.socket_path(),
            selected.active_connections(),
            candidates.len(),
            healthy.len(),
            rr_index
        );

        Some(ConnectionGuard::new(Arc::clone(selected)))
    }

    /// Get the number of workers.
    pub fn worker_count(&self) -> usize {
        self.workers.len()
    }

    /// Get the number of healthy workers.
    pub fn healthy_worker_count(&self) -> usize {
        self.workers.iter().filter(|w| w.is_healthy()).count()
    }

    /// Update a worker's socket path by worker ID.
    ///
    /// RFC-0011 §6A.7: Required for supporting monotonic socket paths during respawn.
    pub fn update_worker_path(&self, worker_id: u64, new_path: String) {
        if let Some(worker) = self.workers.get(worker_id as usize) {
            let old_path = worker.socket_path();
            eprintln!(
                "[LB] update_worker_path: id={} old={} new={}",
                worker_id, old_path, new_path
            );
            worker.update_path(new_path);
            worker.mark_healthy(); // Assume new worker is healthy
        }
    }

    /// Mark a worker as unhealthy by socket path.
    pub fn mark_unhealthy(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path() == socket_path) {
            worker.mark_unhealthy();
        }
    }

    /// Mark a worker as healthy by socket path.
    pub fn mark_healthy(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path() == socket_path) {
            worker.mark_healthy();
        }
    }

    /// Add a new worker to the load balancer.
    pub fn add_worker(&mut self, socket_path: String, worker_id: u64) {
        self.workers
            .push(Arc::new(WorkerNode::new(socket_path, worker_id)));
    }

    /// RFC-0011 §6A.7: Iterate over all workers for Per-Worker Client creation.
    pub fn workers_iter(&self) -> impl Iterator<Item = &WorkerNode> {
        self.workers.iter().map(|w| w.as_ref())
    }

    /// Find a worker by ID.
    pub fn find_by_id(&self, worker_id: u64) -> Option<Arc<WorkerNode>> {
        self.workers
            .iter()
            .find(|w| w.worker_id == worker_id)
            .cloned()
    }

    /// Remove a worker from the load balancer.
    pub fn remove_worker(&mut self, socket_path: &str) {
        self.workers.retain(|w| w.socket_path() != socket_path);
    }

    /// Gate H (DEF-72-H01): Check if a PID is authorized to receive requests.
    /// Returns true if the PID belongs to a known spawned worker.
    pub fn is_authorized_pid(&self, pid: u32) -> bool {
        if pid == 0 {
            return false; // Invalid PID
        }
        self.workers.iter().any(|w| w.pid() == pid)
    }

    /// Register a worker's PID for Gate H authentication.
    pub fn register_worker_pid(&self, worker_id: u64, pid: u32) {
        if let Some(worker) = self.workers.get(worker_id as usize) {
            worker.update_pid(pid);
            eprintln!(
                "[LB] Gate H: Registered PID {} for worker {}",
                pid, worker_id
            );
        }
    }

    /// Get total active connections across all workers.
    pub fn total_active_connections(&self) -> usize {
        self.workers.iter().map(|w| w.active_connections()).sum()
    }

    /// Add a backend by socket path (mark as healthy if exists, or log if not found)
    pub fn add_backend(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path() == socket_path) {
            log::info!(
                "[LB] event=add_backend worker_id={} socket={}",
                worker.worker_id,
                socket_path
            );
            worker.mark_healthy();
        }
    }

    /// Remove a backend by socket path (mark as unhealthy)
    pub fn remove_backend(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path() == socket_path) {
            log::info!(
                "[LB] event=remove_backend worker_id={} socket={}",
                worker.worker_id,
                socket_path
            );
            worker.mark_unhealthy();
        }
    }

    /// Graceful shutdown - wait for all connections to drain.
    ///
    /// RFC-0011: Ensures in-flight requests complete before shutdown.
    pub async fn graceful_shutdown(&self, timeout: Duration) -> Result<(), &'static str> {
        use std::time::Instant;

        let deadline = Instant::now() + timeout;
        let poll_interval = Duration::from_millis(10);

        loop {
            if self.total_active_connections() == 0 {
                return Ok(());
            }

            if Instant::now() >= deadline {
                return Err("Graceful shutdown timeout: connections still active");
            }

            tokio::time::sleep(poll_interval).await;
        }
    }

    /// Wait for at least one worker to become healthy (socket created).
    ///
    /// STB-SOCKET-RACE: Called before accepting requests to ensure workers
    /// have finished creating their sockets.
    pub async fn wait_for_healthy(&self, timeout: Duration) -> bool {
        use std::time::Instant;

        let deadline = Instant::now() + timeout;
        let poll_interval = Duration::from_millis(50);

        while Instant::now() < deadline {
            let mut all_dead = true;
            for worker in &self.workers {
                let current_path = worker.socket_path();

                // 1. Check if socket is open
                if UnixStream::connect(&current_path).await.is_ok() {
                    eprintln!("[LB] Worker {} ready", current_path);
                    worker.mark_healthy();
                    return true;
                }

                // 2. Check if process is still alive (Fail-Fast)
                let pid = worker.pid();
                if pid != 0 {
                    #[cfg(unix)]
                    {
                        if unsafe { libc::kill(pid as i32, 0) == 0 } {
                            all_dead = false;
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        all_dead = false; // Simplified for non-unix
                    }
                } else {
                    all_dead = false; // PID not yet registered
                }
            }

            if all_dead && !self.workers.is_empty() {
                eprintln!(
                    "[LB] CRITICAL: All worker processes died during startup. Aborting wait."
                );
                return false;
            }

            tokio::time::sleep(poll_interval).await;
        }

        eprintln!("[LB] Timeout waiting for healthy workers");
        false
    }

    /// Spawn a background task to actively probe worker health (RFC-0011 C.3).
    ///
    /// Decouples health checks from request handling.
    pub fn spawn_health_checks(&self, interval: Duration) {
        let workers = self.workers.clone();
        tokio::spawn(async move {
            loop {
                for worker in &workers {
                    // Active probing: try to connect to the Unix socket
                    let current_path = worker.socket_path();
                    match UnixStream::connect(&current_path).await {
                        Ok(_) => {
                            // If it was unhealthy, mark it healthy again
                            if !worker.is_healthy() {
                                eprintln!("[LB] Worker {} recovered", current_path);
                                worker.mark_healthy();
                            } else {
                                // Reset consecutive failures on success
                                worker.record_success();
                            }
                        }
                        Err(e) => {
                            eprintln!("[LB] Health check failed for {}: {}", current_path, e);
                            // Record failure (may trigger circuit breaker)
                            worker.record_failure();
                        }
                    }
                }
                tokio::time::sleep(interval).await;
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_node_connection_tracking() {
        let node = WorkerNode::new(
            std::env::temp_dir()
                .join("test.sock")
                .to_string_lossy()
                .to_string(),
            1,
        );
        node.mark_healthy();
        assert_eq!(node.active_connections(), 0);

        node.increment();
        assert_eq!(node.active_connections(), 1);

        node.increment();
        assert_eq!(node.active_connections(), 2);

        node.decrement();
        assert_eq!(node.active_connections(), 1);

        node.decrement();
        assert_eq!(node.active_connections(), 0);
    }

    #[test]
    fn test_connection_guard_raii() {
        let node = Arc::new(WorkerNode::new(
            std::env::temp_dir()
                .join("test.sock")
                .to_string_lossy()
                .to_string(),
            1,
        ));
        node.mark_healthy();
        assert_eq!(node.active_connections(), 0);

        {
            let _guard = ConnectionGuard::new(Arc::clone(&node));
            assert_eq!(node.active_connections(), 1);

            {
                let _guard2 = ConnectionGuard::new(Arc::clone(&node));
                assert_eq!(node.active_connections(), 2);
            }

            assert_eq!(node.active_connections(), 1);
        }

        assert_eq!(node.active_connections(), 0);
    }

    #[test]
    fn test_load_balancer_least_connections() {
        let lb = LoadBalancer::new(vec![
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .to_string(),
            std::env::temp_dir()
                .join("w2.sock")
                .to_string_lossy()
                .to_string(),
            std::env::temp_dir()
                .join("w3.sock")
                .to_string_lossy()
                .to_string(),
        ]);
        for w in &lb.workers {
            w.mark_healthy();
        }

        // Initial state: Workers are unhealthy. Mark them healthy for least-connections test.
        for worker in &lb.workers {
            worker.mark_healthy();
        }

        // First selection should pick any (all have 0 connections)
        let guard1 = lb.select_worker().unwrap();
        let first_path = guard1.socket_path().to_string();

        // Second selection should pick a different worker
        let guard2 = lb.select_worker().unwrap();
        assert_ne!(guard2.socket_path(), first_path);

        // Third selection should pick the remaining worker
        let guard3 = lb.select_worker().unwrap();
        assert_ne!(guard3.socket_path(), guard2.socket_path());

        // Drop guards
        drop(guard1);
        drop(guard2);
        drop(guard3);

        // All connections released
        assert_eq!(lb.workers[0].active_connections(), 0);
        assert_eq!(lb.workers[1].active_connections(), 0);
        assert_eq!(lb.workers[2].active_connections(), 0);
    }

    #[test]
    fn test_load_balancer_unhealthy_worker() {
        let w1 = std::env::temp_dir()
            .join("w1.sock")
            .to_string_lossy()
            .to_string();
        let w2 = std::env::temp_dir()
            .join("w2.sock")
            .to_string_lossy()
            .to_string();
        let lb = LoadBalancer::new(vec![w1.clone(), w2.clone()]);
        for w in &lb.workers {
            w.mark_healthy();
        }

        lb.mark_unhealthy(&w1);

        // Should always select healthy worker
        for _ in 0..10 {
            let guard = lb.select_worker().unwrap();
            assert_eq!(guard.socket_path(), w2);
            drop(guard);
        }

        // Mark healthy again
        lb.mark_healthy(&w1);
        assert_eq!(lb.healthy_worker_count(), 2);
    }

    #[test]
    fn test_load_balancer_no_healthy_workers() {
        let w1 = std::env::temp_dir()
            .join("w1.sock")
            .to_string_lossy()
            .to_string();
        let lb = LoadBalancer::new(vec![w1.clone()]);
        lb.mark_unhealthy(&w1);

        assert!(lb.select_worker().is_none());
    }

    // =========================================================================
    // TDD Cycle 2.2: Dynamic Worker Registration
    // =========================================================================

    #[test]
    fn test_add_worker_increases_count() {
        let mut lb = LoadBalancer::new(vec![]);
        assert_eq!(lb.worker_count(), 0);

        lb.add_worker(
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .to_string(),
            1,
        );
        lb.mark_healthy(
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .as_ref(),
        );
        assert_eq!(lb.worker_count(), 1);

        lb.add_worker(
            std::env::temp_dir()
                .join("w2.sock")
                .to_string_lossy()
                .to_string(),
            2,
        );
        lb.mark_healthy(
            std::env::temp_dir()
                .join("w2.sock")
                .to_string_lossy()
                .as_ref(),
        );
        assert_eq!(lb.worker_count(), 2);

        // New worker should be selectable (mark healthy first)
        lb.workers.last().unwrap().mark_healthy();
        let guard = lb.select_worker();
        assert!(guard.is_some());
    }

    #[test]
    fn test_remove_worker_decreases_count() {
        let w1 = std::env::temp_dir()
            .join("w1.sock")
            .to_string_lossy()
            .to_string();
        let w2 = std::env::temp_dir()
            .join("w2.sock")
            .to_string_lossy()
            .to_string();
        let mut lb = LoadBalancer::new(vec![w1.clone(), w2.clone()]);
        for w in &lb.workers {
            w.mark_healthy();
        }
        assert_eq!(lb.worker_count(), 2);

        lb.remove_worker(&w1);
        assert_eq!(lb.worker_count(), 1);

        // Mark remaining w2 healthy
        lb.mark_healthy(&w2);

        // Only w2 should remain
        let guard = lb.select_worker().unwrap();
        assert_eq!(guard.socket_path(), w2);
    }

    // =========================================================================
    // TDD Cycle 2.4: Graceful Shutdown
    // =========================================================================

    #[tokio::test]
    async fn test_graceful_shutdown_waits_for_connections() {
        use std::time::Duration;

        let lb = LoadBalancer::new(vec![
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .to_string(),
        ]);
        lb.workers[0].mark_healthy();

        // Acquire a connection
        lb.mark_healthy(&lb.workers[0].socket_path().to_string());
        let guard = lb.select_worker().unwrap();
        assert_eq!(lb.workers[0].active_connections(), 1);

        // Start shutdown in background (should wait for drain)
        let lb_clone = lb.clone();
        let shutdown_handle =
            tokio::spawn(async move { lb_clone.graceful_shutdown(Duration::from_secs(5)).await });

        // Give time for shutdown to start
        tokio::time::sleep(Duration::from_millis(50)).await;

        // Drop guard (connection complete)
        drop(guard);

        // Shutdown should complete
        let result = shutdown_handle.await.unwrap();
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_graceful_shutdown_timeout() {
        use std::time::Duration;

        let lb = LoadBalancer::new(vec![
            std::env::temp_dir()
                .join("w1.sock")
                .to_string_lossy()
                .to_string(),
        ]);
        lb.workers[0].mark_healthy();

        // Acquire a connection but don't drop it
        lb.mark_healthy(&lb.workers[0].socket_path().to_string());
        let _guard = lb.select_worker().unwrap();

        // Shutdown with very short timeout should fail
        let result = lb.graceful_shutdown(Duration::from_millis(50)).await;
        assert!(result.is_err(), "Should timeout with active connections");
    }

    #[test]
    fn test_circuit_breaker_threshold() {
        let w1 = std::env::temp_dir()
            .join("w1.sock")
            .to_string_lossy()
            .to_string();
        let lb = LoadBalancer::new(vec![w1]);
        lb.mark_healthy(&lb.workers[0].socket_path().to_string());
        let worker = &lb.workers[0];
        worker.mark_healthy();

        // 1-4 failures: still healthy
        for _ in 1..5 {
            worker.record_failure();
            assert!(worker.is_healthy());
        }

        // 5th failure: UNHEALTHY
        worker.record_failure();
        assert!(
            !worker.is_healthy(),
            "Circuit breaker MUST trip after 5 failures (RFC-0011)"
        );

        // Success: HEALTHY again
        worker.mark_healthy();
        assert!(worker.is_healthy());
    }

    #[test]
    fn test_round_robin_tie_breaker() {
        let w1 = std::env::temp_dir()
            .join("w1.sock")
            .to_string_lossy()
            .to_string();
        let w2 = std::env::temp_dir()
            .join("w2.sock")
            .to_string_lossy()
            .to_string();
        let lb = LoadBalancer::new(vec![w1.clone(), w2.clone()]);
        for w in &lb.workers {
            w.mark_healthy();
        }

        // Both have 0 connections. RR should alternate.
        let g1 = lb.select_worker().unwrap();
        assert_eq!(g1.socket_path(), w1);

        let g2 = lb.select_worker().unwrap();
        assert_eq!(g2.socket_path(), w2);

        let g3 = lb.select_worker().unwrap();
        assert_eq!(
            g3.socket_path(),
            w1,
            "RR tie-breaker MUST alternate when connections are equal"
        );
    }
}
