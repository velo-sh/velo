# RFC-0021: Hybrid Worker Respawn Strategy

| Field       | Value                                  |
|-------------|----------------------------------------|
| Status      | Draft                                  |
| Author      | Velo Team                              |
| Created     | 2026-01-12                             |
| Updated     | 2026-01-12                             |
| Depends On  | RFC-0011, RFC-0013                     |

## Abstract

This RFC proposes upgrading the current polling-based worker death detection to a hybrid SIGCHLD-driven + polling fallback strategy, reducing respawn latency from seconds to near-zero while maintaining reliability.

## Motivation

### Current State (Polling-Only)

```
Worker dies → 1s health check loop detects → Respawn triggered
           │
           └── Up to 1 second latency
```

### Industry Best Practices

| Project   | Strategy                        |
|-----------|--------------------------------|
| Nginx     | SIGCHLD + periodic health check |
| Gunicorn  | SIGCHLD + arbiter loop (1s)     |
| uWSGI     | SIGCHLD + harakiri timeout      |
| systemd   | SIGCHLD + watchdog polling      |

All production-grade process managers use hybrid strategies.

## Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hybrid Respawn Engine                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐ │
│  │   SIGCHLD    │────▶│   Respawn    │◀────│   Health     │ │
│  │  Handler     │     │   Engine     │     │   Polling    │ │
│  │  (Primary)   │     │              │     │  (Fallback)  │ │
│  │  ~0ms delay  │     │              │     │  10s interval│ │
│  └──────────────┘     └──────────────┘     └──────────────┘ │
│                              │                              │
│                              ▼                              │
│                    ┌──────────────┐                         │
│                    │  Backoff +   │                         │
│                    │  Fail-Fast   │                         │
│                    └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### Why Both?

| Mechanism  | Pros                          | Cons                             |
|------------|-------------------------------|----------------------------------|
| **SIGCHLD** | Zero latency, immediate response | Signals can be lost (race), platform differences |
| **Polling** | Reliable, detects zombies     | Latency (seconds)                |

### Implementation

#### 1. SIGCHLD Handler (Primary)

```rust
use signal_hook::iterator::Signals;
use nix::sys::wait::{waitpid, WaitPidFlag};

fn spawn_sigchld_handler(tx: Sender<WorkerEvent>) {
    std::thread::spawn(move || {
        let mut signals = Signals::new(&[libc::SIGCHLD]).unwrap();
        for _ in signals.forever() {
            // Reap all terminated children (non-blocking)
            loop {
                match waitpid(Pid::from_raw(-1), Some(WaitPidFlag::WNOHANG)) {
                    Ok(WaitStatus::Exited(pid, code)) => {
                        log::info!("[SIGCHLD] pid={} exit_code={}", pid, code);
                        let _ = tx.send(WorkerEvent::Died { pid: pid.as_raw() as u32 });
                    }
                    Ok(WaitStatus::Signaled(pid, sig, _)) => {
                        log::warn!("[SIGCHLD] pid={} signal={:?}", pid, sig);
                        let _ = tx.send(WorkerEvent::Died { pid: pid.as_raw() as u32 });
                    }
                    Ok(WaitStatus::StillAlive) | Err(_) => break,
                    _ => continue,
                }
            }
        }
    });
}
```

#### 2. Polling Fallback (Safety Net)

```rust
// Every 10 seconds, verify all workers are alive
// This catches edge cases where SIGCHLD was missed
fn health_check_loop(workers: &[Worker], tx: Sender<WorkerEvent>) {
    loop {
        std::thread::sleep(Duration::from_secs(10));
        for worker in workers {
            if !worker.is_alive() {
                log::warn!("[HEALTH] Fallback detection: worker {} dead", worker.id);
                let _ = tx.send(WorkerEvent::Died { pid: worker.pid });
            }
        }
    }
}
```

#### 3. Unified Respawn Engine

```rust
enum WorkerEvent {
    Died { pid: u32 },
    HealthCheckTimeout { worker_id: u64 },
}

fn respawn_engine(rx: Receiver<WorkerEvent>, workers: &mut [Worker]) {
    let mut tracker = RespawnTracker::new();
    
    for event in rx {
        match event {
            WorkerEvent::Died { pid } => {
                if let Some(worker) = workers.iter_mut().find(|w| w.pid == pid) {
                    if tracker.should_respawn() {
                        // Trigger respawn
                        respawn_worker(worker, &mut tracker);
                    }
                }
            }
            _ => {}
        }
    }
}
```

## Benefits

| Metric                | Current (Polling) | Proposed (Hybrid) |
|-----------------------|-------------------|-------------------|
| Detection latency     | Up to 1s          | ~0ms              |
| Missed death events   | Possible          | Near-zero         |
| CPU overhead          | Constant polling  | Event-driven      |
| Reliability           | Good              | Excellent         |

## Migration Plan

### Phase 1: Add SIGCHLD Handler (Non-Breaking)
- Add SIGCHLD signal handler alongside existing polling
- SIGCHLD triggers immediate respawn
- Polling remains as fallback

### Phase 2: Reduce Polling Frequency
- Change polling interval from 1s to 10s
- SIGCHLD handles fast detection
- Polling becomes safety net only

### Phase 3: Observability
- Add `[SIGCHLD]` structured logs
- Track latency metrics (time from death to respawn)

## Platform Considerations

| Platform | SIGCHLD Support | Notes |
|----------|-----------------|-------|
| Linux    | ✅ Full         | Native support |
| macOS    | ✅ Full         | Native support |
| Windows  | ❌ N/A          | No fork(), use polling only |

## Rollback Strategy

If SIGCHLD handler causes issues:
1. Set `VELO_DISABLE_SIGCHLD=1` to disable
2. Falls back to polling-only mode

## Success Metrics

- Respawn latency p99 < 100ms (down from ~1s)
- Zero missed worker deaths in CI
- No increase in CPU usage

## References

- [Gunicorn Arbiter](https://docs.gunicorn.org/en/stable/design.html)
- [Nginx Master Process](https://nginx.org/en/docs/control.html)
- [systemd Watchdog](https://www.freedesktop.org/software/systemd/man/sd_watchdog_enabled.html)
