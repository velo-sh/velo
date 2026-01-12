# RFC-0021: Unified Process Supervision Strategy

| Field       | Value                                  |
|-------------|----------------------------------------|
| Status      | Draft                                  |
| Author      | Velo Team                              |
| Created     | 2026-01-12                             |
| Updated     | 2026-01-12                             |
| Depends On  | RFC-0011, RFC-0013                     |

## Abstract

This RFC proposes a unified supervision strategy for all critical Velo components using a hybrid SIGCHLD-driven + polling fallback approach, ensuring automatic recovery from failures across the entire runtime.

## Supervised Components

| Component      | Type       | Current State    | Priority |
|----------------|------------|------------------|----------|
| **Workers**    | Child proc | Polling 1s       | P0       |
| **Zygote**     | Child proc | No auto-restart  | P0       |
| **L7 Proxy**   | Tokio task | No supervision   | P1       |
| **Health Srv** | Thread     | No supervision   | P2       |
| **File Watch** | Thread     | No supervision   | P3       |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Unified Supervision Engine                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────┐                                                          │
│  │   SIGCHLD     │──┐                                                       │
│  │   Handler     │  │     ┌────────────────────────────────────────────┐    │
│  │  (Processes)  │  │     │           Supervision Engine               │    │
│  └───────────────┘  ├────▶│                                            │    │
│                     │     │  Workers[]  ─►  respawn via Zygote         │    │
│  ┌───────────────┐  │     │  Zygote     ─►  respawn (full restart)     │    │
│  │   Polling     │──┤     │  Proxy      ─►  respawn tokio task         │    │
│  │  (Fallback)   │  │     │  Health     ─►  respawn thread             │    │
│  │  10s interval │  │     │                                            │    │
│  └───────────────┘  │     └────────────────────────────────────────────┘    │
│                     │                                                       │
│  ┌───────────────┐  │                                                       │
│  │  Task Watcher │──┘     (for Tokio tasks that don't produce SIGCHLD)     │
│  │  (Async poll) │                                                          │
│  └───────────────┘                                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Supervision Strategies

### 1. Workers (SIGCHLD + Polling)

```rust
// SIGCHLD for immediate detection
// Polling (10s) for fallback
enum SupervisionEvent {
    ProcessDied { pid: u32, component: Component },
    TaskFailed { name: String },
    HealthCheckFailed { component: Component },
}

enum Component {
    Worker(u64),  // worker_id
    Zygote,
    Proxy,
    HealthServer,
}
```

### 2. Zygote (SIGCHLD + Polling)

**Current Problem**: If Zygote dies, worker respawn silently fails.

```rust
// Zygote supervision
if !zygote.is_alive() {
    log::error!("[SUPERVISOR] Zygote died! Restarting...");
    zygote = ZygoteLauncher::new(socket_path.clone())
        .with_python(python_path)
        .start(&preload, None, true, &config)?;
    log::info!("[SUPERVISOR] Zygote restarted");
}
```

### 3. L7 Proxy (Tokio Task Supervision)

**Current Problem**: If proxy task panics, the whole server appears dead but process is alive.

```rust
// Use tokio::spawn with JoinHandle monitoring
let proxy_handle = tokio::spawn(async move {
    run_proxy(lb, bind_addr).await
});

// In supervision loop
if proxy_handle.is_finished() {
    match proxy_handle.await {
        Ok(Ok(_)) => log::info!("[PROXY] Graceful shutdown"),
        Ok(Err(e)) => {
            log::error!("[PROXY] Failed: {}, restarting...", e);
            proxy_handle = tokio::spawn(run_proxy(lb.clone(), bind_addr));
        }
        Err(e) => {
            log::error!("[PROXY] Panicked: {}, restarting...", e);
            proxy_handle = tokio::spawn(run_proxy(lb.clone(), bind_addr));
        }
    }
}
```

### 4. Health Server (Thread Supervision)

```rust
// Health server thread with heartbeat
let health_handle = std::thread::spawn(move || {
    run_health_server(bind_addr)
});

// Check thread is alive via try_join with timeout
// If dead, respawn
```

## Unified Event System

```rust
enum SupervisionEvent {
    // From SIGCHLD handler
    ChildExited { pid: u32, exit_code: i32 },
    ChildSignaled { pid: u32, signal: i32 },
    
    // From polling/task watcher
    ComponentUnhealthy { component: Component },
    TaskCompleted { name: String, result: Result<(), String> },
}

struct Supervisor {
    workers: Vec<Worker>,
    zygote: Option<ZygoteLauncher>,
    proxy_handle: Option<JoinHandle<()>>,
    health_handle: Option<JoinHandle<()>>,
    
    event_rx: Receiver<SupervisionEvent>,
    respawn_tracker: RespawnTracker,
}

impl Supervisor {
    fn run(&mut self) {
        for event in self.event_rx.iter() {
            match event {
                SupervisionEvent::ChildExited { pid, .. } => {
                    self.handle_process_death(pid);
                }
                SupervisionEvent::ComponentUnhealthy { component } => {
                    self.handle_unhealthy(component);
                }
                SupervisionEvent::TaskCompleted { name, result } => {
                    if result.is_err() {
                        self.respawn_task(&name);
                    }
                }
            }
        }
    }
    
    fn handle_process_death(&mut self, pid: u32) {
        // Check if it's a worker
        if let Some(worker) = self.workers.iter_mut().find(|w| w.pid == pid) {
            self.respawn_worker(worker);
            return;
        }
        
        // Check if it's Zygote
        if self.zygote.as_ref().map(|z| z.pid) == Some(pid) {
            self.respawn_zygote();
        }
    }
}
```

## Migration Plan

### Phase 1: Unified Event System
- Create `SupervisionEvent` enum
- Create `Supervisor` struct
- Migrate worker respawn to use events

### Phase 2: Add SIGCHLD Handler
- Add SIGCHLD signal handler
- Reduce polling to 10s fallback
- Add Zygote supervision

### Phase 3: Tokio Task Supervision
- Monitor Proxy JoinHandle
- Auto-restart on panic/error

### Phase 4: Full Coverage
- Add Health Server supervision
- Add File Watcher supervision (optional)

## Configuration

```toml
# config/constants.toml
[supervision]
# Enable SIGCHLD-driven detection (disable for debugging)
sigchld_enabled = true

# Polling interval for fallback detection
polling_interval_secs = 10

# Max consecutive failures before giving up
fail_fast_limit = 5

# Components to supervise (all by default)
supervised_components = ["workers", "zygote", "proxy", "health"]
```

## Observability

All supervision events use structured logging:

```
[SUPERVISOR] event=child_exited pid=1234 component=worker_0
[SUPERVISOR] event=respawn component=worker_0 status=success new_pid=5678
[SUPERVISOR] event=zygote_restart reason=process_exit
[SUPERVISOR] event=proxy_restart reason=task_panic
```

## Platform Considerations

| Platform | Process (SIGCHLD) | Tokio Tasks | Notes |
|----------|-------------------|-------------|-------|
| Linux    | ✅ Full           | ✅ Full     | |
| macOS    | ✅ Full           | ✅ Full     | |
| Windows  | ❌ Polling only   | ✅ Full     | No fork() |

## Success Metrics

| Component   | Detection Latency | Recovery Time |
|-------------|-------------------|---------------|
| Workers     | ~0ms (SIGCHLD)    | < 1s          |
| Zygote      | ~0ms (SIGCHLD)    | < 2s          |
| Proxy       | < 100ms           | < 100ms       |
| Health Srv  | < 100ms           | < 100ms       |

## References

- [Erlang OTP Supervision](https://www.erlang.org/doc/design_principles/sup_princ.html)
- [systemd Service Supervision](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Tokio Task Supervision Patterns](https://tokio.rs/tokio/topics/shutdown)
