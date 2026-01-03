use std::sync::atomic::{AtomicU64, Ordering};

pub struct GraphMetrics {
    pub graph_hits: AtomicU64,
    pub graph_misses: AtomicU64,
    pub scc_fallbacks: AtomicU64,
    pub validation_failures: AtomicU64,
    pub graph_deserialize_latency_us: AtomicU64,
}

static METRICS: GraphMetrics = GraphMetrics {
    graph_hits: AtomicU64::new(0),
    graph_misses: AtomicU64::new(0),
    scc_fallbacks: AtomicU64::new(0),
    validation_failures: AtomicU64::new(0),
    graph_deserialize_latency_us: AtomicU64::new(0),
};

pub fn record_hit() {
    METRICS.graph_hits.fetch_add(1, Ordering::Relaxed);
}

pub fn record_miss() {
    METRICS.graph_misses.fetch_add(1, Ordering::Relaxed);
}

pub fn record_scc_fallback() {
    METRICS.scc_fallbacks.fetch_add(1, Ordering::Relaxed);
}

pub fn record_validation_failure() {
    METRICS.validation_failures.fetch_add(1, Ordering::Relaxed);
}

pub fn record_deserialize_latency(us: u64) {
    METRICS
        .graph_deserialize_latency_us
        .store(us, Ordering::Relaxed);
}

pub fn report_metrics() {
    let hits = METRICS.graph_hits.load(Ordering::Relaxed);
    let misses = METRICS.graph_misses.load(Ordering::Relaxed);
    let sccs = METRICS.scc_fallbacks.load(Ordering::Relaxed);
    let failures = METRICS.validation_failures.load(Ordering::Relaxed);
    let latency = METRICS.graph_deserialize_latency_us.load(Ordering::Relaxed);

    if hits > 0 || misses > 0 || sccs > 0 || failures > 0 || latency > 0 {
        if std::env::var("VELO_REPORT_METRICS").is_ok() {
            let json = serde_json::json!({
                "graph_hits": hits,
                "graph_misses": misses,
                "scc_fallbacks": sccs,
                "validation_failures": failures,
                "graph_deserialize_latency_us": latency,
            });
            eprintln!("{}", serde_json::to_string(&json).unwrap());
        } else {
            eprintln!("\n📊 Velo Static Graph Metrics (Phase 6.0)");
            eprintln!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
            eprintln!("  Hits:              {}", hits);
            eprintln!("  Misses:            {}", misses);
            eprintln!("  SCC Fallbacks:     {}", sccs);
            eprintln!("  Validation Fails:  {}", failures);
            eprintln!("  Load Latency:      {}μs", latency);
            eprintln!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
        }
    }
}
