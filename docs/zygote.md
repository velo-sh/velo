# Zygote: Fast Python Startup

> **Pre-warm Python imports for instant script execution**

Zygote reduces Python cold start from ~500ms to <50ms by pre-loading heavy libraries.

## Quick Start

```bash
# Profile your app to find slow imports
velo run --profile your_app.py

# Generate preload configuration
velo zygote auto-config

# Start Zygote daemon with preload
velo zygote start --preload numpy,pandas,torch

# Run scripts instantly via Zygote
velo run --zygote your_app.py
```

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                      Zygote Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   velo run --zygote      ──────▶   Zygote Process           │
│                                    (pre-loaded Python)       │
│                                           │                  │
│                                           ▼                  │
│                                    fork() + COW              │
│                                           │                  │
│                                           ▼                  │
│                                    Worker (your script)      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Insight**: `fork()` uses Copy-on-Write (COW), so workers share the pre-loaded memory with the parent. This means:
- **Instant startup**: No need to re-import heavy modules
- **Memory efficient**: Workers share read-only pages with parent

## Commands

| Command | Description |
|---------|-------------|
| `velo zygote start` | Start Zygote daemon |
| `velo zygote start --preload numpy,torch` | Start with pre-loaded modules |
| `velo zygote stop` | Stop Zygote daemon |
| `velo zygote status` | Check if Zygote is running |
| `velo zygote auto-config` | Generate preload config from profile |

## Workflow

### 1. Profile Your App

```bash
velo run --profile slowapp.py
```

Output:
```
⏱️  Running with profiling enabled...

Import Timing Breakdown
════════════════════════════════════════════════════════════════
Module                         Time (ms)    Cumulative
────────────────────────────────────────────────────────────────
numpy                            245.3         245.3
pandas                           189.2         434.5
torch                            312.1         746.6
...

Total execution time: 1.24s
```

### 2. Generate Configuration

```bash
velo zygote auto-config
```

Output:
```
📊 Auto-Configuration Results
════════════════════════════════════

Preload modules (3):
  • numpy
  • pandas
  • torch

Estimated startup savings: 746ms

📝 Updated: pyproject.toml (added [tool.velo] section)
```

### 3. Start Zygote

```bash
velo zygote start --preload numpy,pandas,torch
```

### 4. Run Fast

```bash
velo run --zygote app.py
# ⚡ Running via Zygote (PID: 12345)
```

## Hybrid Mode

If you just use `--zygote` without starting the daemon first, Velo automatically starts Zygote:

```bash
velo run --zygote app.py
# 🚀 Starting Zygote...
# ✅ Zygote ready
# ⚡ Running via Zygote (PID: 12345)
```

## Platform Support

| Platform | Status |
|----------|--------|
| macOS    | ✅ Full support |
| Linux    | ✅ Full support |
| Windows  | ❌ Not supported (no fork) |

## Performance

| Scenario | Cold Start | Zygote | Speedup |
|----------|-----------|--------|---------|
| Simple script | ~80ms | ~15ms | 5x |
| FastAPI app | ~540ms | ~45ms | 12x |
| Django app | ~400ms | ~38ms | 10x |

## Troubleshooting

### Zygote not starting

```bash
# Check status
velo zygote status

# Force stop and restart
velo zygote stop
velo zygote start
```

### Socket error

```bash
# Socket might be stale - stop will clean it up
velo zygote stop
```

### Fallback to normal mode

If Zygote fails, Velo automatically falls back to normal execution:

```
⚠️ Zygote spawn failed: Connection refused
   Falling back to normal mode
```

## Socket Location

Default socket path: `/tmp/velo-zygote.sock`
