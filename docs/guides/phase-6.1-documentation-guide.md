# Phase 6.1 Documentation Guide

> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Author**: Documentation Expert  
> **Date**: 2026-01-04  
> **Status**: APPROVED

---

## 1. Quick Start Template

The README Quick Start section must enable first server in <2 minutes.

```markdown
## Quick Start

### 1. Install Velo
```bash
curl -fsSL https://velo.sh/install.sh | sh
# or: cargo install velo
```

### 2. Run Your App
```bash
cd your-fastapi-project
velo serve
```

That's it! 🎉

Velo automatically:
- ✨ Detects your FastAPI/Django/Flask app
- 📊 Loads your import graph (0 stat() calls!)  
- 🔄 Watches for changes and restarts in <50ms

### What You'll See
```
✨ Detected FastAPI app in 'main.py'
⏱  Timing: Load 2ms | Graph 1ms | Init 5ms | Total 8ms
📊 Graph: 127 modules (saved ~540 stat() calls)
🟢 Listening on http://0.0.0.0:8000
```
```

---

## 2. CLI Help Text Specification

### velo serve --help

```
⚡ Velo - The Python runtime that runs your code faster

Usage: velo serve [OPTIONS] [APP]

Arguments:
  [APP]  Python ASGI/WSGI application (e.g., main:app)
         If not provided, Velo auto-detects your app.

Server Options:
  --host <HOST>              Bind host [default: 127.0.0.1]
  --port <PORT>              Bind port [default: 8000]
  --bind <HOST:PORT>         Unified bind address
  --workers <N>              Number of workers [default: 1]
  --timeout <SECONDS>        Graceful shutdown timeout [default: 30]

Development Options:
  --reload                   Enable instant restart on file changes
  --no-reload                Disable file watching
  --reload-dir <PATH>        Watch only this directory
  --reload-delay <MS>        Debounce delay [default: 300]

Mode:
  --dev                      Development mode (implies --reload)
  --prod                     Production mode (auto workers, no reload)

Output:
  -v, --verbose              Increase verbosity (-v, -vv, -vvv)
  --output-format <FORMAT>   Output format: human, plain, json
  --log-format <FORMAT>      Log format: text, json

Production:
  --health-bind <HOST:PORT>  Health check endpoint
  --pid-file <PATH>          Write PID to file

General:
  -h, --help                 Print help
  -V, --version              Print version

Examples:
  velo serve                 # Auto-detect and run
  velo serve main:app        # Explicit app
  velo serve --dev           # Development with hot reload
  velo serve --prod          # Production optimized

Learn more: https://velo.sh/docs/serve
```

### velo analyze --help

```
⚡ Velo - Analyze your Python project

Usage: velo analyze [OPTIONS]

Options:
  --graph                    Show static import graph analysis
  --json                     Output as JSON
  -o, --output <FILE>        Write output to file
  -h, --help                 Print help

Examples:
  velo analyze --graph              # Show savings report
  velo analyze --graph --json       # Export as JSON

Learn more: https://velo.sh/docs/analyze
```

---

## 3. Migration Guide

### From Uvicorn

```markdown
## Migrating from Uvicorn

| Before (Uvicorn) | After (Velo) |
|------------------|--------------|
| `uvicorn main:app --reload` | `velo serve` |
| `uvicorn main:app --host 0.0.0.0 --port 8000` | `velo serve --bind 0.0.0.0:8000` |
| `uvicorn main:app --workers 4` | `velo serve --prod` |
| `uvicorn main:app --reload-dir src/` | `velo serve --reload-dir src/` |

### What Changes

✅ **Faster startup**: <10ms vs ~500ms  
✅ **Zero config**: Auto-detects your app  
✅ **Instant reload**: <50ms vs 2-3 seconds  
✅ **Import optimization**: 0 stat() calls  

### What Stays the Same

- Your application code (no changes needed)
- Environment variables (PORT, HOST, WORKERS)
- ASGI compatibility
- Uvicorn underneath (Velo is a wrapper)
```

### From Gunicorn

```markdown
## Migrating from Gunicorn

| Before (Gunicorn) | After (Velo) |
|-------------------|--------------|
| `gunicorn wsgi:application` | `velo serve` |
| `gunicorn -w 4 -b 0.0.0.0:8000 wsgi:application` | `velo serve --prod --bind 0.0.0.0:8000` |
| `gunicorn --reload wsgi:application` | `velo serve --dev` |

### Django Projects

```bash
# Before
gunicorn myproject.wsgi:application

# After
velo serve
# Velo auto-detects wsgi.py and uses gunicorn
```
```

---

## 4. Troubleshooting Guide

```markdown
## Troubleshooting

### "No app detected"

**Cause**: Velo couldn't find a FastAPI/Flask/Django app.

**Solutions**:
1. Ensure your app variable is named `app` or `application`:
   ```python
   app = FastAPI()  # ✅ Detected
   my_app = FastAPI()  # ❌ Not detected
   ```

2. Specify explicitly:
   ```bash
   velo serve mymodule:my_app
   ```

3. Add to pyproject.toml:
   ```toml
   [tool.velo]
   app = "mymodule:my_app"
   ```

---

### "Port already in use"

**Cause**: Another process is using the port.

**Solutions**:
```bash
# Use a different port
velo serve --port 8001

# Find what's using the port
lsof -i :8000

# Kill the process
kill -9 <PID>
```

---

### "uvicorn not found"

**Cause**: uvicorn is not in your dependencies.

**Solution**:
```bash
uv add uvicorn
# or
pip install uvicorn
```

---

### "DJANGO_SETTINGS_MODULE not set"

**Cause**: Django requires this environment variable.

**Solutions**:
```bash
# Set environment variable
export DJANGO_SETTINGS_MODULE=myproject.settings
velo serve

# Or add to pyproject.toml
[tool.velo]
env = { DJANGO_SETTINGS_MODULE = "myproject.settings" }
```

---

### File changes not detected

**macOS**: FSEvents may have 1-2s latency. This is normal.

**Linux**: Check inotify limit:
```bash
cat /proc/sys/fs/inotify/max_user_watches
# If < 65536, increase it:
echo 65536 | sudo tee /proc/sys/fs/inotify/max_user_watches
```

**Docker**: File watching uses polling in containers (500ms delay).
Add `--reload-delay 500` if changes are missed.

---

### "Permission denied" for PID file

**Cause**: Cannot write to `/var/run/velo.pid`.

**Solutions**:
```bash
# Use a different location
velo serve --pid-file ./velo.pid

# Or run with appropriate permissions
sudo velo serve --pid-file /var/run/velo.pid
```
```

---

## 5. Changelog Template

```markdown
## v0.6.1 - The Hook Release (YYYY-MM-DD)

### ✨ New Features

- **`velo serve` - Zero-Config Server** (#123)
  - Auto-detects FastAPI, Flask, Django, Starlette apps
  - Uvicorn/Gunicorn transparent proxy
  - Instant restart (<50ms) on file changes
  - Health check endpoints (`--health-bind`)
  
- **`velo analyze --graph` - Savings Report** (#124)
  - Shows stat() syscalls saved
  - Top connected modules ranking
  - JSON export for tooling

### 🔧 Improvements

- **CLI Polish**
  - Colored output with Velo branding
  - Startup timing breakdown
  - Industry-standard error messages (Rust-style)
  - Verbosity levels (-v, -vv, -vvv)

- **Production Ready**
  - PID file support (`--pid-file`)
  - JSON log format (`--log-format json`)
  - SIGTERM handling for Kubernetes

### 📚 Documentation

- Quick Start guide
- Migration guide from uvicorn/gunicorn
- Troubleshooting section
- Shell completion scripts

### 🔒 Security

- Command injection prevention
- Path traversal protection
- Environment sanitization

### 🐛 Bug Fixes

- (None in this release)

### ⚠️ Breaking Changes

- (None in this release)
```

---

## 6. Voice and Tone Guidelines

### Do ✅

- Use **active voice**: "Velo detects" not "The app is detected"
- Use **second person**: "your app" not "the user's app"
- Be **concise**: Bullet points over paragraphs
- Be **friendly**: "That's it! 🎉" is appropriate
- Include **examples**: Every feature needs a runnable example
- Provide **copy-pasteable commands**: Users should be able to paste and run

### Don't ❌

- Don't use jargon without explanation
- Don't assume prior knowledge of Velo internals
- Don't be condescending ("Simply do..." implies it's easy)
- Don't use passive voice in instructions
- Don't forget the "why" - explain benefits, not just features

### Error Message Voice

```
❌ Bad: "Error 127: App not found"
✅ Good: "Failed to detect ASGI app in 'main.py'"

❌ Bad: "Invalid input"
✅ Good: "Port must be a number between 1 and 65535, got 'abc'"

❌ Bad: "Operation failed"
✅ Good: "Port 8000 is already in use. Try: velo serve --port 8001"
```

---

## 7. Examples Directory Structure

```
examples/
├── README.md                    # Overview of examples
├── fastapi-simple/
│   ├── main.py                  # Minimal FastAPI app
│   ├── pyproject.toml
│   └── README.md                # How to run
├── fastapi-full/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── routers/
│   │   └── models/
│   ├── pyproject.toml
│   └── README.md
├── django-basic/
│   ├── myproject/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── manage.py
│   ├── pyproject.toml
│   └── README.md
├── flask-factory/
│   ├── app/
│   │   ├── __init__.py          # create_app() factory
│   │   └── routes.py
│   ├── pyproject.toml
│   └── README.md
└── production-docker/
    ├── Dockerfile
    ├── docker-compose.yml
    ├── app/
    └── README.md
```

---

## 8. Shell Completion Scripts

### Generate with Clap

```rust
// In build.rs or main.rs
use clap_complete::{generate_to, shells::*};

fn generate_completions() {
    let mut cmd = Cli::command();
    generate_to(Bash, &mut cmd, "velo", "completions/")?;
    generate_to(Zsh, &mut cmd, "velo", "completions/")?;
    generate_to(Fish, &mut cmd, "velo", "completions/")?;
}
```

### Installation Instructions

```markdown
## Shell Completions

### Bash
```bash
velo completions bash > /etc/bash_completion.d/velo
# or for user-only:
velo completions bash >> ~/.bash_completion
```

### Zsh
```bash
velo completions zsh > ~/.zsh/completions/_velo
```

### Fish
```bash
velo completions fish > ~/.config/fish/completions/velo.fish
```
```

---

## 9. Documentation Expert Findings Summary

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| DOC-P0-001 | No Quick Start spec | P0 | §1 |
| DOC-P0-002 | CLI help text undefined | P0 | §2 |
| DOC-P0-003 | Migration guide missing | P0 | §3 |
| DOC-P0-004 | Troubleshooting missing | P0 | §4 |
| DOC-P0-005 | Changelog template missing | P0 | §5 |
| DOC-P1-001 | No voice/tone guide | P1 | §6 |
| DOC-P1-002 | No man page | P1 | Use clap |
| DOC-P1-003 | No shell completions | P1 | §8 |
| DOC-P1-004 | No examples directory | P1 | §7 |

---

**Status**: Documentation guide ready for v0.6.1 implementation.
