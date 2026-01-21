//! Self-Healing File Watcher
//!
//! This module implements a file watcher that survives worker crashes
//! and maintains a persistent watch loop.

use anyhow::Result;
use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::path::Path;
use std::sync::Arc;
use std::sync::mpsc::{Receiver, channel};
use std::thread;
use std::time::Duration;

/// Trait for handling file change events.
pub trait WatchHandler: Send + Sync + 'static {
    fn on_change(&self, path: &str);
}

pub struct VibeWatcher {
    handler: Arc<dyn WatchHandler>,
    _watcher: Option<RecommendedWatcher>,
}

impl VibeWatcher {
    pub fn new<H: WatchHandler>(handler: H) -> Self {
        Self {
            handler: Arc::new(handler),
            _watcher: None,
        }
    }

    pub fn watch(&mut self, path: &str) -> Result<()> {
        let (tx, rx) = channel::<notify::Result<Event>>();

        let mut watcher = RecommendedWatcher::new(tx, Config::default())?;
        watcher.watch(Path::new(path), RecursiveMode::Recursive)?;

        let handler = self.handler.clone();

        thread::spawn(move || {
            Self::event_loop(rx, handler);
        });

        self._watcher = Some(watcher);
        Ok(())
    }

    fn event_loop(rx: Receiver<notify::Result<Event>>, handler: Arc<dyn WatchHandler>) {
        use std::collections::HashMap;
        use std::time::Instant;

        let mut last_events: HashMap<String, Instant> = HashMap::new();
        let debounce_duration = Duration::from_millis(200);

        loop {
            match rx.recv() {
                Ok(Ok(event)) => {
                    log::trace!("Watcher event: {:?}", event);
                    // On some platforms, we get Busy/None or other types.
                    // We trigger on any non-metadata event for now to be safe.
                    if !event.kind.is_access() && !event.kind.is_other() {
                        for path in event.paths {
                            if let Some(p_str) = path.to_str() {
                                // Ignore hidden files (starting with dot) or backup files
                                let is_hidden = path
                                    .file_name()
                                    .and_then(|s| s.to_str())
                                    .map(|s| s.starts_with('.'))
                                    .unwrap_or(false);

                                if is_hidden || p_str.ends_with('~') {
                                    continue;
                                }

                                let now = Instant::now();
                                if let Some(last_time) = last_events.get(p_str)
                                    && now.duration_since(*last_time) < debounce_duration
                                {
                                    continue;
                                }
                                last_events.insert(p_str.to_string(), now);
                                handler.on_change(p_str);
                            }
                        }
                    }
                }
                Ok(Err(e)) => {
                    log::error!("Watcher internal error: {:?}", e);
                }
                Err(_) => {
                    // Channel closed
                    break;
                }
            }
        }
    }
}
