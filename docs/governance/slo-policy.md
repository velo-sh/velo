# Velo SLO Policy

> **"Without measurement, optimization is guessing."**

**Version**: 1.0  
**Author**: Velo Architect  
**Date**: 2026-01-27

---

## 1. Service Level Objectives (SLOs)

### 1.1 Performance SLOs

| Metric | Target | Measurement |
|:---|:---|:---|
| **Zygote Fork Latency P50** | < 20ms | Prometheus histogram |
| **Zygote Fork Latency P99** | < 100ms | Prometheus histogram |
| **Cold Start (first request)** | < 200ms | E2E benchmark |
| **Memory per Worker** | < 50MB baseline | RSS monitoring |

### 1.2 Reliability SLOs

| Metric | Target | Measurement |
|:---|:---|:---|
| **Fork Success Rate** | > 99.9% | Counter ratio |
| **Graceful Shutdown** | 100% clean | Exit code monitoring |
| **Compatibility Tests** | > 99.5% pass | CI matrix |

---

## 2. Error Budget Policy

### 2.1 Definition

**Error Budget** = 100% - SLO Target

Example: 99.9% fork success → 0.1% error budget → ~43 minutes/month allowed downtime

### 2.2 Budget Consumption

| Usage Level | Action |
|:---|:---|
| < 50% consumed | Normal development velocity |
| 50-80% consumed | Increased monitoring, caution on risky changes |
| > 80% consumed | Feature freeze, focus on stability |
| 100% consumed | All hands on reliability, no new features |

---

## 3. Monitoring Requirements

### 3.1 Required Metrics

```
# Core Performance
velo_zygote_fork_duration_seconds{quantile="0.5"}
velo_zygote_fork_duration_seconds{quantile="0.99"}
velo_zygote_workers_active
velo_zygote_pool_idle_count

# Reliability
velo_zygote_fork_success_total
velo_zygote_fork_failure_total
velo_ipc_message_size_bytes
```

### 3.2 Alerting Thresholds

| Alert | Condition | Severity |
|:---|:---|:---|
| Fork Latency High | P99 > 150ms for 5min | Warning |
| Fork Latency Critical | P99 > 300ms for 2min | Critical |
| Pool Exhausted | idle_count = 0 for 1min | Warning |
| Fork Failures | rate > 1% for 5min | Critical |

---

## 4. Review Cadence

| Review | Frequency | Participants |
|:---|:---|:---|
| SLO Dashboard | Daily | On-call |
| Error Budget | Weekly | Tech Lead |
| SLO Targets | Quarterly | Architect |

---

**Custodian**: Velo Architect  
**Review Cycle**: Quarterly
