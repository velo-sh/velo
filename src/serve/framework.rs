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
}
