//! File watcher for hot reload functionality
//!
//! Implements D6 (notify crate integration) and D7 (debouncing state machine)
//! per RFC-0010 §4.4 and §5.3.1.

use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
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
pub const MAX_WATCHED_FILES: usize = 10_000;

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
    Debouncing { last_event: Instant },
    /// Currently restarting the server
    Restarting { since: Instant },
}

// ============================================================================
// FileWatcher (D6, RFC §5.3.1)
// ============================================================================

/// File watcher with debouncing for hot reload
pub struct FileWatcher {
    watcher: RecommendedWatcher,
    receiver: Receiver<Result<Event, notify::Error>>,
    state: WatcherState,
    debounce_delay: Duration,
    shutdown_flag: Arc<AtomicBool>,
    event_count: usize,
    event_window_start: Instant,
}

impl FileWatcher {
    /// Create a new file watcher
    pub fn new(shutdown_flag: Arc<AtomicBool>, debounce_ms: u64) -> Result<Self, ServeError> {
        let (tx, rx) = mpsc::channel();

        let watcher = RecommendedWatcher::new(
            move |res| {
                let _ = tx.send(res);
            },
            Self::get_config(),
        )
        .map_err(|e| ServeError::WatcherError(e.to_string()))?;

        Ok(Self {
            watcher,
            receiver: rx,
            state: WatcherState::Idle,
            debounce_delay: Duration::from_millis(debounce_ms),
            shutdown_flag,
            event_count: 0,
            event_window_start: Instant::now(),
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

    /// Detect if running in a container (LNX-P0-002)
    #[cfg(target_os = "linux")]
    fn is_container() -> bool {
        use std::path::Path;

        Path::new("/.dockerenv").exists()
            || std::fs::read_to_string("/proc/1/cgroup")
                .map(|s| s.contains("docker") || s.contains("kubepods"))
                .unwrap_or(false)
    }

    /// Start watching a directory
    pub fn watch(&mut self, path: &Path) -> Result<(), ServeError> {
        // Check inotify limit on Linux (LNX-P0-001)
        #[cfg(target_os = "linux")]
        Self::check_inotify_limit();

        self.watcher
            .watch(path, RecursiveMode::Recursive)
            .map_err(|e| ServeError::WatcherError(e.to_string()))
    }

    /// Check inotify watch limit on Linux (LNX-P0-001)
    #[cfg(target_os = "linux")]
    fn check_inotify_limit() {
        if let Ok(limit_str) = std::fs::read_to_string("/proc/sys/fs/inotify/max_user_watches") {
            if let Ok(limit) = limit_str.trim().parse::<usize>() {
                if limit < 65536 {
                    eprintln!("⚠️  Warning: Low inotify limit ({})", limit);
                    eprintln!(
                        "   To fix: echo 65536 | sudo tee /proc/sys/fs/inotify/max_user_watches"
                    );
                }
            }
        }
    }

    /// Poll for file change events
    ///
    /// Returns true if a restart should be triggered
    pub fn poll(&mut self) -> Result<bool, ServeError> {
        // Check for shutdown
        if self.shutdown_flag.load(Ordering::SeqCst) {
            return Ok(false);
        }

        // Process pending events
        while let Ok(result) = self.receiver.try_recv() {
            match result {
                Ok(event) => {
                    if self.should_trigger_reload(&event) {
                        // Rate limiting check (SEC-P0-006)
                        if !self.check_rate_limit() {
                            continue;
                        }
                        self.state = WatcherState::Debouncing {
                            last_event: Instant::now(),
                        };
                    }
                }
                Err(e) => {
                    eprintln!("⚠️  Watch error: {}", e);
                }
            }
        }

        // State machine transitions
        match self.state {
            WatcherState::Idle => Ok(false),
            WatcherState::Debouncing { last_event } => {
                if last_event.elapsed() >= self.debounce_delay {
                    self.state = WatcherState::Restarting {
                        since: Instant::now(),
                    };
                    Ok(true) // Trigger restart
                } else {
                    Ok(false)
                }
            }
            WatcherState::Restarting { since } => {
                // After restart completes, go back to idle
                // Caller should call `restart_complete()` when done
                if since.elapsed() > Duration::from_secs(5) {
                    // Timeout protection
                    self.state = WatcherState::Idle;
                }
                Ok(false)
            }
        }
    }

    /// Check if we're within rate limits (SEC-P0-006)
    fn check_rate_limit(&mut self) -> bool {
        let now = Instant::now();
        let window = Duration::from_secs(1);

        if now.duration_since(self.event_window_start) > window {
            // Reset window
            self.event_window_start = now;
            self.event_count = 1;
            true
        } else {
            self.event_count += 1;
            if self.event_count > MAX_EVENTS_PER_SECOND {
                // Rate limit exceeded
                false
            } else {
                true
            }
        }
    }

    /// Check if an event should trigger a reload
    fn should_trigger_reload(&self, event: &Event) -> bool {
        use notify::EventKind;

        // Only trigger on content modifications
        matches!(
            event.kind,
            EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_)
        ) && event.paths.iter().any(|p| {
            p.extension()
                .map(|ext| ext == "py" || ext == "pyi")
                .unwrap_or(false)
        })
    }

    /// Signal that restart is complete
    pub fn restart_complete(&mut self) {
        self.state = WatcherState::Idle;
    }

    /// Get current state
    pub fn state(&self) -> WatcherState {
        self.state
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_state_is_idle() {
        assert_eq!(WatcherState::default(), WatcherState::Idle);
    }

    #[test]
    fn test_debounce_delay() {
        let shutdown = Arc::new(AtomicBool::new(false));
        let watcher = FileWatcher::new(shutdown, 300);
        assert!(watcher.is_ok());
        let watcher = watcher.unwrap();
        assert_eq!(watcher.debounce_delay, Duration::from_millis(300));
    }

    #[test]
    fn test_state_transitions() {
        let state = WatcherState::Debouncing {
            last_event: Instant::now(),
        };
        assert!(matches!(state, WatcherState::Debouncing { .. }));

        let state = WatcherState::Restarting {
            since: Instant::now(),
        };
        assert!(matches!(state, WatcherState::Restarting { .. }));
    }
}
