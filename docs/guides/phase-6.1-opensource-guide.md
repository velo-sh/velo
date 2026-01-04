# Phase 6.1 Open Source Community Guide

> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Author**: Open Source Community Expert  
> **Date**: 2026-01-04  
> **Status**: APPROVED

---

## 1. CONTRIBUTING.md Template

```markdown
# Contributing to Velo

Thank you for your interest in contributing to Velo! 🎉

## Quick Start

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/velo.git`
3. Create a branch: `git checkout -b feature/my-feature`
4. Make your changes
5. Run tests: `cargo test`
6. Submit a pull request

## Development Setup

```bash
# Prerequisites
- Rust 1.75+ (rustup recommended)
- Python 3.10+ (for testing)
- uv (for Python dependency management)

# Build
cargo build --release

# Run tests
cargo test
pytest tests/

# Run lints
cargo clippy -- -D warnings
cargo fmt --check
```

## Pull Request Process

1. **Title**: Use conventional commits format
   - `feat: add health check endpoint`
   - `fix: correct path traversal validation`
   - `docs: add migration guide`

2. **Description**: Explain what and why

3. **Tests**: Add tests for new features

4. **Review**: Wait for maintainer review

## Code Style

- Follow `rustfmt` defaults
- Use `clippy` with default lints
- Document public APIs with rustdoc
- Keep functions small and focused

## Reporting Issues

- Check existing issues first
- Use issue templates
- Include reproduction steps
- Attach logs with `-vvv` output
```

---

## 2. Code of Conduct (Contributor Covenant)

```markdown
# Code of Conduct

## Our Pledge

We pledge to make participation in our community a harassment-free 
experience for everyone.

## Our Standards

**Positive behaviors:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community

**Unacceptable behaviors:**
- Trolling, insulting comments, personal attacks
- Public or private harassment
- Publishing others' private information

## Enforcement

Report violations to: conduct@velo.sh

## Attribution

This Code of Conduct is adapted from the Contributor Covenant, 
version 2.1, available at https://www.contributor-covenant.org/
```

---

## 3. Issue Templates

### Bug Report

```yaml
# .github/ISSUE_TEMPLATE/bug_report.yml
name: Bug Report
description: Report a bug in Velo
labels: ["bug", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for reporting! Please fill in the details below.
  
  - type: textarea
    id: description
    attributes:
      label: Description
      description: What happened?
    validations:
      required: true
  
  - type: textarea
    id: reproduction
    attributes:
      label: Steps to Reproduce
      description: How can we reproduce this?
      value: |
        1. 
        2. 
        3. 
    validations:
      required: true
  
  - type: textarea
    id: expected
    attributes:
      label: Expected Behavior
      description: What did you expect to happen?
  
  - type: textarea
    id: logs
    attributes:
      label: Logs
      description: Run with `velo -vvv` and paste output
      render: shell
  
  - type: dropdown
    id: os
    attributes:
      label: Operating System
      options:
        - macOS
        - Linux
        - Windows (WSL)
    validations:
      required: true
  
  - type: input
    id: version
    attributes:
      label: Velo Version
      placeholder: v0.6.1
```

### Feature Request

```yaml
# .github/ISSUE_TEMPLATE/feature_request.yml
name: Feature Request
description: Suggest a new feature
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What problem does this solve?
    validations:
      required: true
  
  - type: textarea
    id: solution
    attributes:
      label: Proposed Solution
      description: How would you like it to work?
    validations:
      required: true
  
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: What other solutions did you consider?
```

---

## 4. PR Template

```markdown
<!-- .github/PULL_REQUEST_TEMPLATE.md -->

## Description

<!-- What does this PR do? -->

## Related Issues

<!-- Closes #123 -->

## Checklist

- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] `cargo clippy` passes
- [ ] `cargo fmt` passes

## Screenshots

<!-- If applicable -->
```

---

## 5. Changelog Format (Keep a Changelog)

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature description (#123)

### Changed
- Change description (#124)

### Fixed
- Bug fix description (#125)

## [0.6.1] - 2026-01-XX

### Added
- `velo serve` zero-config server (#100)
- `velo analyze --graph` savings report (#101)
- Health check endpoints (#102)

### Changed
- Improved error messages (#103)

[Unreleased]: https://github.com/velo-sh/velo/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/velo-sh/velo/releases/tag/v0.6.1
```

---

## 6. OSS Findings Summary

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| OSS-P0-001 | CONTRIBUTING.md | P0 | §1 |
| OSS-P0-002 | Code of Conduct | P0 | §2 |
| OSS-P0-003 | Issue templates | P0 | §3 |
| OSS-P1-001 | Public roadmap | P1 | Defer |
| OSS-P1-002 | Community channel | P1 | Defer |
| OSS-P1-003 | Changelog format | P1 | §5 |

---

**Status**: Templates ready for v0.6.1 release.
