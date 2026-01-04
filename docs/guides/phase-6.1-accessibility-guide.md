# Phase 6.1 Accessibility Guide

> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Author**: Accessibility Expert  
> **Date**: 2026-01-04  
> **Status**: APPROVED

---

## 1. Color Blindness Considerations

### Problem: Emoji/Color-Only Indicators

Current design uses colors alone:
```
🟢 Server running    (color-dependent)
🔴 Server stopped    (color-dependent)
⚠️ Warning           (relies on emoji rendering)
```

### Solution: Add Text Labels

```
✅ [OK] Server running on http://localhost:8000
❌ [ERROR] Server stopped: port in use
⚠️ [WARN] Low inotify limit detected
```

### Implementation

```rust
fn format_status(status: Status, message: &str) -> String {
    let (icon, label, color) = match status {
        Status::Ok => ("✅", "OK", Color::Green),
        Status::Error => ("❌", "ERROR", Color::Red),
        Status::Warning => ("⚠️", "WARN", Color::Yellow),
        Status::Info => ("ℹ️", "INFO", Color::Blue),
    };
    
    if use_icons() {
        format!("{} [{}] {}", icon, label, message)
    } else {
        format!("[{}] {}", label, message)
    }
}
```

---

## 2. NO_COLOR Support

### Standard: https://no-color.org/

When `NO_COLOR` environment variable is set, disable all color output.

### Implementation

```rust
fn should_colorize() -> bool {
    // NO_COLOR takes precedence
    if std::env::var("NO_COLOR").is_ok() {
        return false;
    }
    
    // Check if stdout is a TTY
    if !atty::is(atty::Stream::Stdout) {
        return false;
    }
    
    // Check TERM
    if std::env::var("TERM").map(|t| t == "dumb").unwrap_or(false) {
        return false;
    }
    
    true
}
```

### Testing

```bash
# Test with NO_COLOR
NO_COLOR=1 velo serve --dry-run

# Test with piping
velo serve --dry-run | cat
```

---

## 3. Unicode/ASCII Fallback

### Problem: Box Drawing Characters

Current design:
```
╭─────────────────────────────╮
│ ⚡ Velo v0.6.1              │
╰─────────────────────────────╯
```

Some terminals don't render Unicode box drawing.

### Solution: ASCII Fallback

```rust
fn get_box_chars() -> BoxChars {
    if supports_unicode() {
        BoxChars {
            top_left: '╭',
            top_right: '╮',
            bottom_left: '╰',
            bottom_right: '╯',
            horizontal: '─',
            vertical: '│',
        }
    } else {
        BoxChars {
            top_left: '+',
            top_right: '+',
            bottom_left: '+',
            bottom_right: '+',
            horizontal: '-',
            vertical: '|',
        }
    }
}

fn supports_unicode() -> bool {
    std::env::var("LANG")
        .map(|l| l.contains("UTF-8") || l.contains("utf8"))
        .unwrap_or(false)
}
```

ASCII output:
```
+-----------------------------+
| Velo v0.6.1                 |
+-----------------------------+
```

---

## 4. Screen Reader Considerations

### Problem: Progress Indicators

Spinners and progress bars don't work with screen readers:
```
Scanning... ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏
```

### Solution: Text-Based Progress

When `--accessibility` or detected screen reader:
```
[1/3] Scanning project files...
[2/3] Building import graph...
[3/3] Starting server...
```

### Detection

```rust
fn use_simple_progress() -> bool {
    // Explicit flag
    if std::env::var("VELO_ACCESSIBILITY").is_ok() {
        return true;
    }
    
    // Screen reader detection (macOS)
    #[cfg(target_os = "macos")]
    if std::process::Command::new("defaults")
        .args(["read", "com.apple.universalaccess", "voiceOverOnOffKey"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
    {
        return true;
    }
    
    false
}
```

---

## 5. High Contrast Mode

### Environment Variable

```bash
VELO_HIGH_CONTRAST=1 velo serve
```

### Colors

| Element | Normal | High Contrast |
|---------|--------|---------------|
| Success | Green | Bold White |
| Error | Red | Bold White + ❌ |
| Warning | Yellow | Bold White + ⚠️ |
| Info | Cyan | White |

---

## 6. CLI Output Guidelines

### Do ✅

1. **Always include text labels** with icons
2. **Respect NO_COLOR** environment variable
3. **Provide ASCII fallback** for box drawing
4. **Use high contrast** for important messages
5. **Keep output scannable** with consistent formatting

### Don't ❌

1. Don't use color as the **only** indicator
2. Don't use emoji as the **only** status indicator
3. Don't assume Unicode support
4. Don't use animated spinners in non-TTY contexts

---

## 7. Testing Checklist

- [ ] Test with `NO_COLOR=1`
- [ ] Test with `TERM=dumb`
- [ ] Test output piped to file: `velo serve --dry-run > out.txt`
- [ ] Test with macOS VoiceOver enabled
- [ ] Test with non-UTF8 locale: `LANG=C velo serve`
- [ ] Verify all icons have text alternatives

---

## 8. Accessibility Findings Summary

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| A11Y-P0-001 | Emoji-only indicators | P0 | §1 |
| A11Y-P0-002 | Color-only status | P0 | §1 |
| A11Y-P1-001 | NO_COLOR support | P1 | §2 |
| A11Y-P1-002 | Unicode fallback | P1 | §3 |
| A11Y-P1-003 | Screen reader testing | P1 | §4, §7 |

---

**Status**: Accessibility guide ready for v0.6.1 implementation.
