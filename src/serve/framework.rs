//! Framework detection for automatic Zygote preloading
//!
//! Detects web frameworks (FastAPI, Django, Flask) to optimize Zygote startup.

use std::path::Path;

/// Detected web framework type
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Framework {
    FastAPI,
    Django,
    Flask,
    Starlette,
    Unknown,
}

impl std::fmt::Display for Framework {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Framework::FastAPI => write!(f, "FastAPI"),
            Framework::Django => write!(f, "Django"),
            Framework::Flask => write!(f, "Flask"),
            Framework::Starlette => write!(f, "Starlette"),
            Framework::Unknown => write!(f, "Unknown"),
        }
    }
}

/// Detect framework from app module path and project directory
///
/// Strategy:
/// 1. Check pyproject.toml/requirements.txt for framework dependencies
/// 2. Infer from app module name patterns
#[allow(clippy::collapsible_if)]
pub fn detect_framework(app_module: &str, project_dir: &Path) -> Framework {
    // Check pyproject.toml for dependencies
    let pyproject = project_dir.join("pyproject.toml");
    if pyproject.exists() {
        if let Ok(content) = std::fs::read_to_string(&pyproject) {
            return detect_from_deps(&content);
        }
    }

    // Check requirements.txt
    let requirements = project_dir.join("requirements.txt");
    if requirements.exists() {
        if let Ok(content) = std::fs::read_to_string(&requirements) {
            return detect_from_deps(&content);
        }
    }

    // Check uv.lock for dependencies
    let uv_lock = project_dir.join("uv.lock");
    if uv_lock.exists() {
        if let Ok(content) = std::fs::read_to_string(&uv_lock) {
            return detect_from_deps(&content);
        }
    }

    // Infer from module name pattern (e.g., "django.core.wsgi:application")
    if app_module.contains("django") {
        return Framework::Django;
    }

    Framework::Unknown
}

/// Infer Django settings module path
pub fn detect_django_settings(project_dir: &Path) -> Option<String> {
    // Strategy: find settings.py in a subdirectory (recursive depth 2)
    // Common layouts:
    // 1. project/myproj/settings.py
    // 2. project/src/myproj/settings.py
    fn search(current_dir: &Path, depth: u8) -> Option<String> {
        if depth == 0 {
            return None;
        }
        if let Ok(entries) = std::fs::read_dir(current_dir) {
            for entry in entries.flatten() {
                if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                    let path = entry.path();
                    let settings = path.join("settings.py");

                    if settings.exists()
                        && path.join("__init__.py").exists()
                        && let Some(dir_name) = path.file_name().and_then(|n| n.to_str())
                    {
                        // If we are at depth 1, it's "dir_name.settings"
                        // If we crawled deeper, we need to handle that, but for now depth 2 usually means
                        // one level below the root or src.
                        return Some(format!("{}.settings", dir_name));
                    }

                    // Recurse once if we haven't found it
                    if depth > 1
                        && let Some(found) = search(&path, depth - 1)
                    {
                        return Some(found);
                    }
                }
            }
        }
        None
    }

    search(project_dir, 2)
}

/// Detect framework from dependency file contents
fn detect_from_deps(content: &str) -> Framework {
    let content_lower = content.to_lowercase();

    // Check in priority order (most specific first)
    if content_lower.contains("fastapi") {
        Framework::FastAPI
    } else if content_lower.contains("django") {
        Framework::Django
    } else if content_lower.contains("flask") {
        Framework::Flask
    } else if content_lower.contains("starlette") {
        Framework::Starlette
    } else {
        Framework::Unknown
    }
}

/// Get recommended preload modules for a framework
///
/// These modules will be pre-imported in the Zygote process
/// to speed up worker startup.
pub fn get_preload_modules(framework: Framework) -> Vec<&'static str> {
    match framework {
        Framework::FastAPI => vec![
            "fastapi",
            "pydantic",
            "starlette",
            "starlette.routing",
            "starlette.middleware",
        ],
        Framework::Django => vec!["django", "django.core", "django.conf", "django.http"],
        Framework::Flask => vec!["flask", "werkzeug", "jinja2"],
        Framework::Starlette => vec!["starlette", "starlette.routing", "starlette.middleware"],
        Framework::Unknown => vec![],
    }
}

// ============================================================================
// Server Selection (D4, RFC §4.2)
// ============================================================================

/// Server type for running the application
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Server {
    /// Uvicorn for ASGI apps (FastAPI, Starlette)
    Uvicorn,
    /// Gunicorn for WSGI apps (Django, Flask)
    Gunicorn,
}

impl std::fmt::Display for Server {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Server::Uvicorn => write!(f, "uvicorn"),
            Server::Gunicorn => write!(f, "gunicorn"),
        }
    }
}

impl Server {
    /// Get the module name for running with `python -m`
    pub fn module_name(&self) -> &'static str {
        match self {
            Server::Uvicorn => "uvicorn",
            Server::Gunicorn => "gunicorn",
        }
    }

    /// Get the install command hint
    pub fn install_hint(&self) -> &'static str {
        match self {
            Server::Uvicorn => "uv add uvicorn",
            Server::Gunicorn => "uv add gunicorn",
        }
    }
}

/// Get the appropriate server for a framework
///
/// Per RFC §4.2:
/// - FastAPI, Starlette → uvicorn (ASGI)
/// - Django, Flask → gunicorn (WSGI)
pub fn get_server_type(framework: Framework) -> Server {
    match framework {
        Framework::FastAPI | Framework::Starlette => Server::Uvicorn,
        Framework::Django | Framework::Flask => Server::Gunicorn,
        Framework::Unknown => Server::Uvicorn, // Default to uvicorn
    }
}

/// Check if the server is installed
pub fn check_server_installed(server: Server, python_path: &std::path::Path) -> bool {
    use std::process::{Command, Stdio};

    let check_cmd = format!("import {}", server.module_name());
    Command::new(python_path)
        .args(["-c", &check_cmd])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_fastapi_from_pyproject() {
        let content = r#"
[project]
dependencies = ["fastapi", "uvicorn"]
"#;
        assert_eq!(detect_from_deps(content), Framework::FastAPI);
    }

    #[test]
    fn test_detect_django_from_requirements() {
        let content = "Django>=4.0\npsycopg2\n";
        assert_eq!(detect_from_deps(content), Framework::Django);
    }

    #[test]
    fn test_detect_flask() {
        let content = "flask==2.0.0\ngunicorn\n";
        assert_eq!(detect_from_deps(content), Framework::Flask);
    }

    #[test]
    fn test_detect_unknown() {
        let content = "requests\nnumpy\n";
        assert_eq!(detect_from_deps(content), Framework::Unknown);
    }

    #[test]
    fn test_preload_modules_fastapi() {
        let modules = get_preload_modules(Framework::FastAPI);
        assert!(modules.contains(&"fastapi"));
        assert!(modules.contains(&"pydantic"));
    }

    #[test]
    fn test_preload_modules_unknown() {
        let modules = get_preload_modules(Framework::Unknown);
        assert!(modules.is_empty());
    }

    // ========================================================================
    // Server enum tests (D4)
    // ========================================================================

    #[test]
    fn test_server_display_uvicorn() {
        assert_eq!(format!("{}", Server::Uvicorn), "uvicorn");
    }

    #[test]
    fn test_server_display_gunicorn() {
        assert_eq!(format!("{}", Server::Gunicorn), "gunicorn");
    }

    #[test]
    fn test_server_module_name_uvicorn() {
        assert_eq!(Server::Uvicorn.module_name(), "uvicorn");
    }

    #[test]
    fn test_server_module_name_gunicorn() {
        assert_eq!(Server::Gunicorn.module_name(), "gunicorn");
    }

    #[test]
    fn test_server_install_hint_uvicorn() {
        assert_eq!(Server::Uvicorn.install_hint(), "uv add uvicorn");
    }

    #[test]
    fn test_server_install_hint_gunicorn() {
        assert_eq!(Server::Gunicorn.install_hint(), "uv add gunicorn");
    }

    // ========================================================================
    // get_server_type tests (D4)
    // ========================================================================

    #[test]
    fn test_get_server_type_fastapi_returns_uvicorn() {
        let server = get_server_type(Framework::FastAPI);
        assert_eq!(server, Server::Uvicorn);
    }

    #[test]
    fn test_get_server_type_starlette_returns_uvicorn() {
        let server = get_server_type(Framework::Starlette);
        assert_eq!(server, Server::Uvicorn);
    }

    #[test]
    fn test_get_server_type_django_returns_gunicorn() {
        let server = get_server_type(Framework::Django);
        assert_eq!(server, Server::Gunicorn);
    }

    #[test]
    fn test_get_server_type_flask_returns_gunicorn() {
        let server = get_server_type(Framework::Flask);
        assert_eq!(server, Server::Gunicorn);
    }

    #[test]
    fn test_get_server_type_unknown_defaults_to_uvicorn() {
        let server = get_server_type(Framework::Unknown);
        assert_eq!(server, Server::Uvicorn);
    }

    // ========================================================================
    // Preload modules tests - additional
    // ========================================================================

    #[test]
    fn test_preload_modules_django() {
        let modules = get_preload_modules(Framework::Django);
        assert!(modules.contains(&"django"));
        assert!(modules.contains(&"django.core"));
    }

    #[test]
    fn test_preload_modules_flask() {
        let modules = get_preload_modules(Framework::Flask);
        assert!(modules.contains(&"flask"));
        assert!(modules.contains(&"werkzeug"));
    }

    #[test]
    fn test_preload_modules_starlette() {
        let modules = get_preload_modules(Framework::Starlette);
        assert!(modules.contains(&"starlette"));
    }
}
