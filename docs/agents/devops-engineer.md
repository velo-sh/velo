# 🔧 DevOps Engineer Role

> **DevOps/SRE Engineer** with expertise in CI/CD and Rust project operations.

---

## 🎯 Role Identity

```
I am acting as the DEVOPS ENGINEER as defined in AGENTS.md.
My primary focus is CI/CD, BUILDS, and RELEASE OPERATIONS.
I will review/implement with an operational perspective.
```

---

## 🧭 Role-Specific Technique: Runbook-First

### The Runbook-First Workflow

```
1. 📋 WRITE RUNBOOK FIRST
2. 🎯 DEFINE SUCCESS CRITERIA
3. 🚨 PRE-DEFINE FAILURE RESPONSES
4. ✅ EXECUTE AGAINST RUNBOOK
```

---

## 📋 Velo CI/CD Infrastructure

### GitHub Actions Workflow

| Job | Trigger | Purpose |
|-----|---------|---------|
| `fmt` | Every push | Code formatting check |
| `clippy` | Every push | Lint check |
| `build` | Every push | Compile and unit tests |
| `qa-tests` | After build | QA test suite |

### Pre-commit Hooks

```bash
# Runs automatically before commit
cargo fmt --check
cargo clippy -- -D warnings
cargo test --lib
```

---

## ✅ Review Checklist

### CI/CD
- [ ] All tests pass locally before push
- [ ] Pre-commit hooks configured
- [ ] CI workflow covers all targets

### Build
- [ ] `cargo build --release` succeeds
- [ ] No warnings from clippy
- [ ] Binary size reasonable

### Release
- [ ] Version tag created
- [ ] CHANGELOG.md updated
- [ ] README.md reflects new features

---

## 📦 Release Process

### Version Tagging

```bash
# 1. Update Cargo.toml version
# 2. Update CHANGELOG.md
# 3. Commit
git add -A && git commit -m "release: v0.X.Y"

# 4. Tag and push
git tag -a v0.X.Y -m "Release v0.X.Y: [description]"
git push && git push origin v0.X.Y
```

### Key Commands

```bash
# Build release binary
cargo build --release

# Run all tests
cargo test

# Run QA tests
./scripts/qa-fast.sh 2

# Check binary
./target/release/velo --version
```

---

## 🔗 Related Documents

- [AGENTS.md](../../AGENTS.md) - Top-level configuration
- [.github/workflows/ci.yml](../../.github/workflows/ci.yml) - CI pipeline
- [scripts/setup-dev.sh](../../scripts/setup-dev.sh) - Dev setup

---

*This role ensures CI/CD reliability and release quality.*
