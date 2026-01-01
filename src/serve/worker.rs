//! Worker pool management for `velo serve`
//!
//! Manages multiple uvicorn workers with Zygote pre-warming.

use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

/// Worker process handle
pub struct Worker {
    process: Child,
    port: u16,
    started_at: Instant,
}

impl Worker {
    /// Check if worker is still running
    pub fn is_running(&mut self) -> bool {
        match self.process.try_wait() {
            Ok(None) => true,     // Still running
            Ok(Some(_)) => false, // Exited
            Err(_) => false,      // Error checking
        }
    }

    /// Get worker startup time
    pub fn uptime(&self) -> Duration {
        self.started_at.elapsed()
    }

    /// Kill the worker
    pub fn kill(&mut self) -> Result<()> {
        self.process.kill().context("Failed to kill worker")?;
        self.process.wait()?;
        Ok(())
    }

    /// Get worker port
    pub fn port(&self) -> u16 {
        self.port
    }
}

/// Worker pool for managing multiple uvicorn instances
pub struct WorkerPool {
    workers: Vec<Worker>,
    base_port: u16,
    python_path: std::path::PathBuf,
    app: String,
    project_dir: std::path::PathBuf,
}

impl WorkerPool {
    /// Create a new worker pool
    pub fn new(python_path: &Path, app: &str, project_dir: &Path, base_port: u16) -> Self {
        Self {
            workers: Vec::new(),
            base_port,
            python_path: python_path.to_path_buf(),
            app: app.to_string(),
            project_dir: project_dir.to_path_buf(),
        }
    }

    /// Spawn N workers
    pub fn spawn_workers(&mut self, count: u32, host: &str) -> Result<()> {
        for i in 0..count {
            let port = self.base_port + i as u16;
            let worker = self.spawn_single_worker(host, port)?;
            self.workers.push(worker);
        }
        Ok(())
    }

    /// Spawn a single worker on specified port
    fn spawn_single_worker(&self, host: &str, port: u16) -> Result<Worker> {
        let mut cmd = Command::new(&self.python_path);
        cmd.arg("-m")
            .arg("uvicorn")
            .arg(&self.app)
            .arg("--host")
            .arg(host)
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&self.project_dir)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());

        let process = cmd.spawn().context("Failed to spawn uvicorn worker")?;

        Ok(Worker {
            process,
            port,
            started_at: Instant::now(),
        })
    }

    /// Check health of all workers, restart dead ones
    pub fn health_check(&mut self, host: &str) -> Result<usize> {
        let mut restarted = 0;
        let mut dead_indices = Vec::new();

        for (i, worker) in self.workers.iter_mut().enumerate() {
            if !worker.is_running() {
                dead_indices.push(i);
            }
        }

        for i in dead_indices.into_iter().rev() {
            let port = self.workers[i].port;
            self.workers.remove(i);

            eprintln!("♻️  Restarting dead worker on port {}", port);
            let worker = self.spawn_single_worker(host, port)?;
            self.workers.push(worker);
            restarted += 1;
        }

        Ok(restarted)
    }

    /// Get number of active workers
    pub fn active_count(&mut self) -> usize {
        let mut count = 0;
        for worker in &mut self.workers {
            if worker.is_running() {
                count += 1;
            }
        }
        count
    }

    /// Shutdown all workers
    pub fn shutdown(&mut self) {
        for worker in &mut self.workers {
            let _ = worker.kill();
        }
        self.workers.clear();
    }

    /// Wait for a signal and run health checks periodically
    pub fn run_supervisor(&mut self, host: &str) -> Result<()> {
        // Set up signal handlers
        ctrlc_handler(|| {});

        eprintln!(
            "📊 Supervisor running, {} workers active",
            self.active_count()
        );
        eprintln!("   Press Ctrl+C to stop\n");

        while !shutdown_requested() {
            std::thread::sleep(Duration::from_secs(5));

            let restarted = self.health_check(host)?;
            if restarted > 0 {
                eprintln!("📊 Health check: {} workers restarted", restarted);
            }
        }

        eprintln!("\n🛑 Shutting down workers...");
        self.shutdown();
        eprintln!("✅ All workers stopped");

        Ok(())
    }
}

impl Drop for WorkerPool {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// Global shutdown flag for signal handling
#[cfg(unix)]
static SHUTDOWN_REQUESTED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

/// Set up Ctrl+C handler using simple atomic flag
#[cfg(unix)]
fn ctrlc_handler<F: FnOnce() + Send + 'static>(_handler: F) {
    use std::sync::Once;
    static INIT: Once = Once::new();

    INIT.call_once(|| unsafe {
        libc::signal(libc::SIGINT, sigint_handler as libc::sighandler_t);
        libc::signal(libc::SIGTERM, sigint_handler as libc::sighandler_t);
    });

    extern "C" fn sigint_handler(_: libc::c_int) {
        SHUTDOWN_REQUESTED.store(true, std::sync::atomic::Ordering::SeqCst);
    }
}

/// Check if shutdown was requested via signal
#[cfg(unix)]
pub fn shutdown_requested() -> bool {
    SHUTDOWN_REQUESTED.load(std::sync::atomic::Ordering::SeqCst)
}

#[cfg(not(unix))]
fn ctrlc_handler<F: FnOnce() + Send + 'static>(_handler: F) {
    // On non-Unix, just ignore - will need proper Windows handling
}

#[cfg(not(unix))]
pub fn shutdown_requested() -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_pool_new() {
        let pool = WorkerPool::new(
            Path::new("/usr/bin/python3"),
            "main:app",
            Path::new("/tmp"),
            8000,
        );
        assert_eq!(pool.base_port, 8000);
        assert_eq!(pool.app, "main:app");
    }
}
