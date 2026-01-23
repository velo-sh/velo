//! RFC-0038-ext: Source Code Snippet Extraction
//!
//! Extracts code context snippets from Python source files for AI-native diagnostics.
//! Implements security mitigations SEC-001 (path traversal), SEC-002 (secret redaction),
//! and PANIC-001 (rayon panic handling).

use rayon::prelude::*;
use rustpython_ast::{self as ast, Stmt};
use rustpython_parser::parse;
use std::panic;
use std::path::Path;

/// Maximum source file size to prevent DoS (1MB)
const MAX_SOURCE_SIZE: u64 = 1_048_576;

/// Code snippet extracted from a Python module
#[derive(Debug, Clone)]
pub struct CodeSnippet {
    /// Function/class signature, e.g. "def init_extension() -> None:"
    pub signature: String,
    /// First N lines of the function/class body
    pub lines: Vec<String>,
    /// 1-indexed line number where the snippet starts
    pub start_line: u32,
}

/// SEC-001: Validate file path against allowlist to prevent path traversal
fn is_safe_file_path(path: &Path) -> bool {
    // Must be absolute path
    if !path.is_absolute() {
        return false;
    }

    let path_str = path.to_string_lossy();

    // Reject frozen modules and special paths
    if path_str.starts_with('<') {
        return false;
    }

    // Safe directory patterns
    let safe_patterns = [
        "/lib/python",
        "/usr/lib/python",
        "/.venv/",
        "/venv/",
        "/site-packages/",
        "/dist-packages/",
        "/.local/lib/",
    ];

    // Allow if in known safe directories
    if safe_patterns.iter().any(|p| path_str.contains(p)) {
        return true;
    }

    // Allow if within current working directory (project sources)
    if let Ok(cwd) = std::env::current_dir()
        && path.starts_with(&cwd)
    {
        return true;
    }

    false
}

/// Read source file safely with size limit
fn read_source_safely(path: &Path) -> Option<String> {
    // Check file exists
    if !path.exists() {
        return None;
    }

    // Check extension - skip C extensions
    if let Some(ext) = path.extension() {
        let ext_str = ext.to_string_lossy().to_lowercase();
        if ext_str == "so" || ext_str == "pyd" || ext_str == "pyc" {
            return None;
        }
    }

    // Check file size
    let metadata = std::fs::metadata(path).ok()?;
    if metadata.len() > MAX_SOURCE_SIZE {
        return None;
    }

    std::fs::read_to_string(path).ok()
}

/// SEC-002: Sanitize snippet lines to redact potential secrets
fn sanitize_snippet_line(line: &str) -> String {
    let secret_patterns = [
        "KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "CREDENTIAL",
        "API_KEY",
    ];

    // Check if line contains assignment with secret-like variable
    let upper = line.to_uppercase();
    if secret_patterns.iter().any(|p| upper.contains(p))
        && (line.contains('=') || line.contains(':'))
    {
        return "# [REDACTED - Potential Secret]".to_string();
    }
    line.to_string()
}

/// Extract signature from a function definition
fn extract_function_signature(
    name: &str,
    args: &ast::Arguments,
    returns: &Option<Box<ast::Expr>>,
) -> String {
    let mut sig = format!("def {}(", name);

    // Simplified args representation
    let mut arg_strs: Vec<String> = Vec::new();
    for arg in &args.args {
        arg_strs.push(arg.def.arg.to_string());
    }
    sig.push_str(&arg_strs.join(", "));
    sig.push(')');

    if returns.is_some() {
        sig.push_str(" -> ...");
    }
    sig.push(':');
    sig
}

/// Extract signature from a class definition
fn extract_class_signature(name: &str, bases: &[ast::Expr]) -> String {
    let mut sig = format!("class {}", name);
    if !bases.is_empty() {
        sig.push('(');
        sig.push_str(&bases.iter().map(|_| "...").collect::<Vec<_>>().join(", "));
        sig.push(')');
    }
    sig.push(':');
    sig
}

/// Calculate 1-indexed line number from byte offset
fn byte_offset_to_line(source: &str, byte_offset: u32) -> u32 {
    let offset = byte_offset as usize;
    let prefix = &source[..std::cmp::min(offset, source.len())];
    (prefix.matches('\n').count() + 1) as u32
}

/// Extract code snippet from first function or class in module
fn extract_from_stmt(stmt: &Stmt, source: &str, source_lines: &[&str]) -> Option<CodeSnippet> {
    match stmt {
        Stmt::FunctionDef(f) => {
            let signature = extract_function_signature(&f.name, &f.args, &f.returns);
            let start_line = byte_offset_to_line(source, f.range.start().to_u32());

            let lines: Vec<String> = source_lines
                .iter()
                .skip((start_line.saturating_sub(1)) as usize)
                .take(5)
                .map(|l| sanitize_snippet_line(l))
                .collect();

            Some(CodeSnippet {
                signature,
                lines,
                start_line,
            })
        }
        Stmt::AsyncFunctionDef(f) => {
            let signature = format!(
                "async {}",
                extract_function_signature(&f.name, &f.args, &f.returns)
            );
            let start_line = byte_offset_to_line(source, f.range.start().to_u32());

            let lines: Vec<String> = source_lines
                .iter()
                .skip((start_line.saturating_sub(1)) as usize)
                .take(5)
                .map(|l| sanitize_snippet_line(l))
                .collect();

            Some(CodeSnippet {
                signature,
                lines,
                start_line,
            })
        }
        Stmt::ClassDef(c) => {
            let signature = extract_class_signature(&c.name, &c.bases);
            let start_line = byte_offset_to_line(source, c.range.start().to_u32());

            let lines: Vec<String> = source_lines
                .iter()
                .skip((start_line.saturating_sub(1)) as usize)
                .take(5)
                .map(|l| sanitize_snippet_line(l))
                .collect();

            Some(CodeSnippet {
                signature,
                lines,
                start_line,
            })
        }
        _ => None,
    }
}

/// Extract module entry snippet from a Python source file
pub fn extract_module_entry_snippet(file_path: &Path) -> Option<CodeSnippet> {
    // SEC-001: Validate path first
    if !is_safe_file_path(file_path) {
        return None;
    }

    // Read source safely
    let source = read_source_safely(file_path)?;
    let source_lines: Vec<&str> = source.lines().collect();

    // Parse AST
    let ast = parse(&source, rustpython_parser::Mode::Module, "<source>").ok()?;

    let body = match ast {
        ast::Mod::Module(ast::ModModule { body, .. }) => body,
        _ => return None,
    };

    // Find first function or class definition
    for stmt in &body {
        if let Some(snippet) = extract_from_stmt(stmt, &source, &source_lines) {
            return Some(snippet);
        }
    }

    None
}

/// Extract snippets for multiple imports in parallel (only top 5)
/// PANIC-001: Uses catch_unwind to handle parsing panics gracefully
pub fn extract_snippets_parallel(
    file_paths: &[Option<std::path::PathBuf>],
) -> Vec<Option<CodeSnippet>> {
    file_paths
        .par_iter()
        .take(5)
        .map(|path_opt| {
            path_opt.as_ref().and_then(|path| {
                // PANIC-001: Catch any panics during parsing
                panic::catch_unwind(|| extract_module_entry_snippet(path)).unwrap_or(None)
            })
        })
        .collect()
}

// ============================================================================
// TESTS
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tempfile::tempdir;

    /// Test extraction logic directly (bypasses path validation)
    fn extract_from_source(source: &str) -> Option<CodeSnippet> {
        use rustpython_ast::{self as ast};
        use rustpython_parser::parse;

        let source_lines: Vec<&str> = source.lines().collect();
        let ast = parse(source, rustpython_parser::Mode::Module, "<source>").ok()?;

        let body = match ast {
            ast::Mod::Module(ast::ModModule { body, .. }) => body,
            _ => return None,
        };

        for stmt in &body {
            if let Some(snippet) = extract_from_stmt(stmt, source, &source_lines) {
                return Some(snippet);
            }
        }
        None
    }

    #[test]
    fn test_extract_function_snippet() {
        let source = "def hello():\n    '''Docstring'''\n    print('world')\n";
        let snippet = extract_from_source(source);

        assert!(snippet.is_some());
        let s = snippet.unwrap();
        assert!(s.signature.contains("def hello"));
        assert_eq!(s.start_line, 1);
        assert_eq!(s.lines.len(), 3);
    }

    #[test]
    fn test_extract_class_snippet() {
        let source = "class Foo:\n    '''A class'''\n    pass\n";
        let snippet = extract_from_source(source);

        assert!(snippet.is_some());
        let s = snippet.unwrap();
        assert!(s.signature.contains("class Foo"));
    }

    #[test]
    fn test_missing_source_graceful() {
        let path = PathBuf::from("/nonexistent/file.py");
        let snippet = extract_module_entry_snippet(&path);
        assert!(snippet.is_none());
    }

    #[test]
    fn test_so_extension_rejected() {
        let dir = tempdir().unwrap();
        let file = dir.path().join("test.so");
        std::fs::write(&file, "binary content").unwrap();

        let old_cwd = std::env::current_dir().unwrap();
        std::env::set_current_dir(dir.path()).unwrap();

        let snippet = extract_module_entry_snippet(&file);

        std::env::set_current_dir(old_cwd).unwrap();

        assert!(snippet.is_none());
    }

    #[test]
    fn test_secret_redaction() {
        let line = "API_KEY = 'sk-secret123'";
        let sanitized = sanitize_snippet_line(line);
        assert!(sanitized.contains("REDACTED"));
    }

    #[test]
    fn test_safe_path_site_packages() {
        let path = PathBuf::from("/usr/lib/python3.11/site-packages/numpy/__init__.py");
        assert!(is_safe_file_path(&path));
    }

    #[test]
    fn test_unsafe_path_etc() {
        let path = PathBuf::from("/etc/passwd");
        assert!(!is_safe_file_path(&path));
    }

    #[test]
    fn test_frozen_module_rejected() {
        let path = PathBuf::from("<frozen importlib._bootstrap>");
        assert!(!is_safe_file_path(&path));
    }
}
