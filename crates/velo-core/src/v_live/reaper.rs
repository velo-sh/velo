//! Greedy Reaper Implementation
//!
//! This module provides the logic to clean up zombie processes
//! using a non-blocking waitpid loop.

#[cfg(unix)]
use nix::sys::wait::{WaitPidFlag, WaitStatus, waitpid};

/// Reaps all available zombie processes in a non-blocking way.
/// Returns the number of processes reaped.
#[cfg(unix)]
pub fn reap_zombies() -> usize {
    let mut count = 0;
    loop {
        match waitpid(None, Some(WaitPidFlag::WNOHANG)) {
            Ok(WaitStatus::Exited(pid, status)) => {
                log::debug!("Reaped process {} with status {}", pid, status);
                count += 1;
            }
            Ok(WaitStatus::Signaled(pid, signal, core_dumped)) => {
                log::debug!(
                    "Reaped process {} killed by signal {:?}, core dumped: {}",
                    pid,
                    signal,
                    core_dumped
                );
                count += 1;
            }
            Ok(WaitStatus::StillAlive) => {
                // No more zombies to reap right now
                break;
            }
            Err(nix::Error::ECHILD) => {
                // No child processes at all
                break;
            }
            Err(e) => {
                log::error!("Error while reaping zombies: {}", e);
                break;
            }
            _ => {
                // Other statuses (stopped, continued) - we don't count them as reaped
                // but we continue the loop if we want to be truly greedy,
                // though usually WNOHANG with None (WaitAll) will return StillAlive if nothing changed.
                break;
            }
        }
    }
    count
}

#[cfg(not(unix))]
pub fn reap_zombies() -> usize {
    // No-op for non-unix platforms
    0
}
