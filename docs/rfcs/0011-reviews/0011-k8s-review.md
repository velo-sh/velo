# RFC-0011 Cloud Native / Kubernetes Review

> **Status**: ✅ APPROVED with Critical Actions  
> **Parent**: [RFC-0011](../0011-zygote-worker-integration.md)

---

## Critical Issues

### 🔴 CPU Quota Awareness

`os.cpu_count()` returns physical cores, not K8s limits!

```rust
// Read Cgroups v2
fn get_cpu_quota() -> Option<usize> {
    let max = std::fs::read_to_string("/sys/fs/cgroup/cpu.max").ok()?;
    // Parse quota/period
}
```

### 🔴 Graceful Shutdown

1. SIGTERM received → Set readiness = false
2. Stop accepting connections
3. Drain in-flight requests
4. Terminate workers
5. Exit

### 🔴 Deep Health Check

`/healthz` must ping workers, not just return 200.

---

**K8s Sign-off**: ✅ Approved with Actions
