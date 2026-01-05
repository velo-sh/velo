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
    /// Path to the worker's Unix socket.
    pub socket_path: String,
    /// Unique worker ID for connection pooling authority.
    pub worker_id: u64,
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
        Self {
            socket_path,
            worker_id,
            active_connections: AtomicUsize::new(0),
            consecutive_failures: AtomicUsize::new(0),
            healthy: std::sync::atomic::AtomicBool::new(true),
        }
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
    pub fn socket_path(&self) -> &str {
        &self.worker.socket_path
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
/// RFC-0011 B.2.2: Uses least-connections strategy.
#[derive(Debug, Clone)]
pub struct LoadBalancer {
    workers: Vec<Arc<WorkerNode>>,
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
        Self { workers }
    }

    /// Select a worker using least-connections strategy.
    ///
    /// Returns a ConnectionGuard that automatically tracks the connection.
    /// Returns None if no healthy workers are available.
    pub fn select_worker(&self) -> Option<ConnectionGuard> {
        self.workers
            .iter()
            .filter(|w| w.is_healthy())
            .min_by_key(|w| w.active_connections())
            .map(|w| ConnectionGuard::new(Arc::clone(w)))
    }

    /// Get the number of workers.
    pub fn worker_count(&self) -> usize {
        self.workers.len()
    }

    /// Get the number of healthy workers.
    pub fn healthy_worker_count(&self) -> usize {
        self.workers.iter().filter(|w| w.is_healthy()).count()
    }

    /// Mark a worker as unhealthy by socket path.
    pub fn mark_unhealthy(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path == socket_path) {
            worker.mark_unhealthy();
        }
    }

    /// Mark a worker as healthy by socket path.
    pub fn mark_healthy(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path == socket_path) {
            worker.mark_healthy();
        }
    }

    /// Add a new worker to the load balancer.
    pub fn add_worker(&mut self, socket_path: String, worker_id: u64) {
        self.workers
            .push(Arc::new(WorkerNode::new(socket_path, worker_id)));
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
        self.workers.retain(|w| w.socket_path != socket_path);
    }

    /// Get total active connections across all workers.
    pub fn total_active_connections(&self) -> usize {
        self.workers.iter().map(|w| w.active_connections()).sum()
    }

    /// Add a backend by socket path (mark as healthy if exists, or log if not found)
    pub fn add_backend(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path == socket_path) {
            worker.mark_healthy();
        }
    }

    /// Remove a backend by socket path (mark as unhealthy)
    pub fn remove_backend(&self, socket_path: &str) {
        if let Some(worker) = self.workers.iter().find(|w| w.socket_path == socket_path) {
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

    /// Spawn a background task to actively probe worker health (RFC-0011 C.3).
    ///
    /// Decouples health checks from request handling.
    pub fn spawn_health_checks(&self, interval: Duration) {
        let workers = self.workers.clone();
        tokio::spawn(async move {
            loop {
                for worker in &workers {
                    // Active probing: try to connect to the Unix socket
                    match UnixStream::connect(&worker.socket_path).await {
                        Ok(_) => {
                            // If it was unhealthy, mark it healthy again
                            if !worker.is_healthy() {
                                worker.mark_healthy();
                            } else {
                                // Reset consecutive failures on success
                                worker.record_success();
                            }
                        }
                        Err(_) => {
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
        let node = WorkerNode::new("/tmp/test.sock".to_string(), 1);
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
        let node = Arc::new(WorkerNode::new("/tmp/test.sock".to_string(), 1));
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
            "/tmp/w1.sock".to_string(),
            "/tmp/w2.sock".to_string(),
            "/tmp/w3.sock".to_string(),
        ]);

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
        let lb = LoadBalancer::new(vec!["/tmp/w1.sock".to_string(), "/tmp/w2.sock".to_string()]);

        lb.mark_unhealthy("/tmp/w1.sock");

        // Should always select healthy worker
        for _ in 0..10 {
            let guard = lb.select_worker().unwrap();
            assert_eq!(guard.socket_path(), "/tmp/w2.sock");
            drop(guard);
        }

        // Mark healthy again
        lb.mark_healthy("/tmp/w1.sock");
        assert_eq!(lb.healthy_worker_count(), 2);
    }

    #[test]
    fn test_load_balancer_no_healthy_workers() {
        let lb = LoadBalancer::new(vec!["/tmp/w1.sock".to_string()]);
        lb.mark_unhealthy("/tmp/w1.sock");

        assert!(lb.select_worker().is_none());
    }

    // =========================================================================
    // TDD Cycle 2.2: Dynamic Worker Registration
    // =========================================================================

    #[test]
    fn test_add_worker_increases_count() {
        let mut lb = LoadBalancer::new(vec![]);
        assert_eq!(lb.worker_count(), 0);

        lb.add_worker("/tmp/w1.sock".to_string(), 1);
        assert_eq!(lb.worker_count(), 1);

        lb.add_worker("/tmp/w2.sock".to_string(), 2);
        assert_eq!(lb.worker_count(), 2);

        // New worker should be selectable
        let guard = lb.select_worker();
        assert!(guard.is_some());
    }

    #[test]
    fn test_remove_worker_decreases_count() {
        let mut lb =
            LoadBalancer::new(vec!["/tmp/w1.sock".to_string(), "/tmp/w2.sock".to_string()]);
        assert_eq!(lb.worker_count(), 2);

        lb.remove_worker("/tmp/w1.sock");
        assert_eq!(lb.worker_count(), 1);

        // Only w2 should remain
        let guard = lb.select_worker().unwrap();
        assert_eq!(guard.socket_path(), "/tmp/w2.sock");
    }

    // =========================================================================
    // TDD Cycle 2.4: Graceful Shutdown
    // =========================================================================

    #[tokio::test]
    async fn test_graceful_shutdown_waits_for_connections() {
        use std::time::Duration;

        let lb = LoadBalancer::new(vec!["/tmp/w1.sock".to_string()]);

        // Acquire a connection
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

        let lb = LoadBalancer::new(vec!["/tmp/w1.sock".to_string()]);

        // Acquire a connection but don't drop it
        let _guard = lb.select_worker().unwrap();

        // Shutdown with very short timeout should fail
        let result = lb.graceful_shutdown(Duration::from_millis(50)).await;
        assert!(result.is_err(), "Should timeout with active connections");
    }
}
