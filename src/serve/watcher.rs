//! File watcher for hot reload functionality
//!
//! Implements D6 (notify crate integration) and D7 (debouncing state machine)
//! per RFC-0010 §4.4 and §5.3.1.

use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{
    Mutex,
    mpsc::{Receiver, channel},
};
use std::time::{Duration, Instant};

use crate::serve::error::ServeError;

// ============================================================================
// Configuration Constants (RFC §4.4)
// ============================================================================

/// Default debounce delay in milliseconds
pub const DEFAULT_DEBOUNCE_MS: u64 = 300;

/// Maximum events per second before rate limiting kicks in (SEC-P0-006)
pub const MAX_EVENTS_PER_SECOND: usize = 100;

/// Maximum number of watched files before warning
pub const MAX_WATCHED_FILES: usize = 5_000;

// ============================================================================
// Watcher State Machine (D7, RFC §4.4)
// ============================================================================

/// State machine for debouncing file events
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum WatcherState {
    /// No recent events, waiting for changes
    #[default]
    Idle,
    /// Received event, waiting for debounce period
    /// `first_event` allows enforcing a hard-cap to prevent starvation (STB-RS-002)
    Debouncing {
        last_event: Instant,
        first_event: Instant,
    },
    /// Currently restarting the server
    Restarting { since: Instant },
}

// ============================================================================
// FileWatcher (D6, RFC §5.3.1)
// ============================================================================

/// File watcher with debouncing for hot reload
pub struct FileWatcher {
    /// Internal state protected by mutex to allow shared mutation (Sync)
    inner: Mutex<FileWatcherInner>,
    /// Global shutdown flag
    pub shutdown_flag: Arc<AtomicBool>,
}

struct FileWatcherInner {
    watcher: RecommendedWatcher,
    receiver: Receiver<Result<Event, notify::Error>>,
    state: WatcherState,
    debounce_delay: Duration,
    event_count: usize,
    event_window_start: Instant,
}

impl FileWatcher {
    /// Create a new file watcher
    pub fn new(shutdown_flag: Arc<AtomicBool>, debounce_ms: u64) -> Result<Self, ServeError> {
        let (tx, rx) = channel();

        let watcher = RecommendedWatcher::new(
            move |res| {
                let _ = tx.send(res);
            },
            Self::get_config(),
        )
        .map_err(|e| ServeError::WatcherError(e.to_string()))?;

        Ok(Self {
            inner: Mutex::new(FileWatcherInner {
                watcher,
                receiver: rx,
                state: WatcherState::Idle,
                debounce_delay: Duration::from_millis(debounce_ms),
                event_count: 0,
                event_window_start: Instant::now(),
            }),
            shutdown_flag,
        })
    }

    /// Get platform-specific watcher configuration
    fn get_config() -> Config {
        let mut config = Config::default();

        // macOS: Request low-latency FSEvents (MAC-P0-001)
        #[cfg(target_os = "macos")]
        {
            config = config.with_poll_interval(Duration::from_millis(100));
        }

        // Linux container detection (LNX-P0-002)
        #[cfg(target_os = "linux")]
        {
            if Self::is_container() {
                eprintln!("[Velo] Container detected, using poll mode for file watching");
                config = config.with_poll_interval(Duration::from_millis(500));
            }
        }

        config
    }

    /// Detect if running inside a container
    #[cfg(target_os = "linux")]
    fn is_container() -> bool {
        Path::new("/.dockerenv").exists()
            || std::fs::read_to_string("/proc/1/cgroup")
                .map(|s| s.contains("docker") || s.contains("containerd") || s.contains("kubepods"))
                .unwrap_or(false)
    }

    /// Add a path to be watched
    pub fn watch(&self, path: &Path) -> Result<(), ServeError> {
        let mut inner = self.inner.lock().unwrap();
        inner
            .watcher
            .watch(path, RecursiveMode::Recursive)
            .map_err(|e| ServeError::WatcherError(e.to_string()))
    }

    /// Poll for changes. Returns Ok(true) if restart should be triggered.
    pub fn poll(&self) -> Result<bool, ServeError> {
        // Check for shutdown
        if self.shutdown_flag.load(Ordering::SeqCst) {
            return Ok(false);
        }

        let mut inner = self.inner.lock().unwrap();

        // Periodic rate limit reset
        if inner.event_window_start.elapsed() >= Duration::from_secs(1) {
            inner.event_count = 0;
            inner.event_window_start = Instant::now();
        }

        // Process pending events
        while let Ok(result) = inner.receiver.try_recv() {
            match result {
                Ok(event) => {
                    if inner.should_trigger_reload(&event) {
                        // Rate limiting check (SEC-P0-006)
                        if !inner.check_rate_limit() {
                            continue;
                        }

                        let now = Instant::now();
                        match inner.state {
                            WatcherState::Debouncing { first_event, .. } => {
                                inner.state = WatcherState::Debouncing {
                                    last_event: now,
                                    first_event,
                                };
                            }
                            _ => {
                                inner.state = WatcherState::Debouncing {
                                    last_event: now,
                                    first_event: now,
                                };
                            }
                        }
                    }
                }
                Err(e) => {
                    return Err(ServeError::WatcherError(e.to_string()));
                }
            }
        }

        // State machine transitions
        match inner.state {
            WatcherState::Idle => Ok(false),
            WatcherState::Debouncing {
                last_event,
                first_event,
            } => {
                let debounce_elapsed = last_event.elapsed();
                let total_elapsed = first_event.elapsed();

                // STB-RS-002: Hard-cap of 2 seconds to prevent debouncer starvation
                let hard_cap = Duration::from_secs(2);

                if debounce_elapsed >= inner.debounce_delay || total_elapsed >= hard_cap {
                    if total_elapsed >= hard_cap {
                        eprintln!(
                            "⚠️  Watcher hard-cap reached ({:.1}s), forcing restart",
                            total_elapsed.as_secs_f64()
                        );
                    }
                    inner.state = WatcherState::Restarting {
                        since: Instant::now(),
                    };
                    Ok(true) // Trigger restart
                } else {
                    Ok(false)
                }
            }
            WatcherState::Restarting { since } => {
                // Minimum time in restarting state to avoid thrashing
                if since.elapsed() >= Duration::from_millis(500) {
                    inner.state = WatcherState::Idle;
                }
                Ok(false)
            }
        }
    }

    /// Reset state to idle
    pub fn restart_complete(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.state = WatcherState::Idle;
    }
}

impl FileWatcherInner {
    /// Check if we're within rate limits (SEC-P0-006)
    fn check_rate_limit(&mut self) -> bool {
        self.event_count += 1;
        if self.event_count > MAX_EVENTS_PER_SECOND {
            if self.event_count == MAX_EVENTS_PER_SECOND + 1 {
                eprintln!("⚠️  Excessive file events, rate limiting hot-reload");
            }
            return false;
        }
        true
    }

    /// Filter events that should trigger a reload
    fn should_trigger_reload(&self, event: &Event) -> bool {
        // Ignore events without paths
        if event.paths.is_empty() {
            return false;
        }

        // Only watch for data modifications or file creations/deletions
        match event.kind {
            notify::EventKind::Modify(notify::event::ModifyKind::Data(_))
            | notify::EventKind::Create(_)
            | notify::EventKind::Remove(_) => {
                // Check if any of the affected files are Python files
                event
                    .paths
                    .iter()
                    .any(|p| p.extension().map(|ext| ext == "py").unwrap_or(false))
            }
            _ => false,
        }
    }
}
