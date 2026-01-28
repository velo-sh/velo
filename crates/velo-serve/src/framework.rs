//! App protocol detection for the serve command.
//!
//! Avoids hardcoded framework lists by probing the app object at runtime.

use std::path::Path;
use std::process::Command;

/// Detected application protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppProtocol {
    Asgi,
    Wsgi,
    Unknown,
}

impl std::fmt::Display for AppProtocol {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AppProtocol::Asgi => write!(f, "ASGI"),
            AppProtocol::Wsgi => write!(f, "WSGI"),
            AppProtocol::Unknown => write!(f, "Unknown"),
        }
    }
}

const PROTOCOL_PROBE_SCRIPT: &str = r#"
import importlib
import inspect
import sys

module_name = sys.argv[1]
raw_app = sys.argv[2]
is_factory = raw_app.endswith("()")
app_name = raw_app[:-2] if is_factory else raw_app

try:
    mod = importlib.import_module(module_name)
    app = getattr(mod, app_name)
    if is_factory:
        app = app()
except Exception:
    sys.exit(2)

def is_asgi(obj):
    if inspect.iscoroutinefunction(obj):
        return True
    call = getattr(obj, "__call__", None)
    if call and inspect.iscoroutinefunction(call):
        return True
    return False

def classify_by_signature(obj):
    call = obj
    if not inspect.isfunction(obj) and not inspect.ismethod(obj):
        call = getattr(obj, "__call__", obj)
    try:
        sig = inspect.signature(call)
    except (TypeError, ValueError):
        return None
    params = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    arity = len(params)
    if arity >= 3:
        return "asgi"
    if arity == 2:
        return "wsgi"
    return None

if is_asgi(app):
    print("asgi")
    sys.exit(0)
if callable(app):
    classified = classify_by_signature(app)
    if classified == "asgi":
        print("asgi")
        sys.exit(0)
    if classified == "wsgi":
        print("wsgi")
        sys.exit(0)
    print("wsgi")
    sys.exit(0)
print("unknown")
sys.exit(3)
"#;

/// Detect ASGI/WSGI protocol by importing the app object.
pub fn detect_app_protocol(
    python_path: &Path,
    project_dir: &Path,
    module: &str,
    app: &str,
) -> AppProtocol {
    let output = Command::new(python_path)
        .args(["-c", PROTOCOL_PROBE_SCRIPT, module, app])
        .current_dir(project_dir)
        .output();

    match output {
        Ok(out) if out.status.success() => match String::from_utf8_lossy(&out.stdout).trim() {
            "asgi" => AppProtocol::Asgi,
            "wsgi" => AppProtocol::Wsgi,
            _ => AppProtocol::Unknown,
        },
        _ => AppProtocol::Unknown,
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
    /// RSGI for Rust-native high-performance orchestration (RFC-0019)
    RSGI,
}

impl std::fmt::Display for Server {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Server::Uvicorn => write!(f, "uvicorn"),
            Server::Gunicorn => write!(f, "gunicorn"),
            Server::RSGI => write!(f, "rsgi"),
        }
    }
}

impl Server {
    /// Get the module name for running with `python -m`
    pub fn module_name(&self) -> &'static str {
        match self {
            Server::Uvicorn => "uvicorn",
            Server::Gunicorn => "gunicorn",
            Server::RSGI => "rsgi",
        }
    }

    /// Get the install command hint
    pub fn install_hint(&self) -> &'static str {
        match self {
            Server::Uvicorn => "uv add uvicorn",
            Server::Gunicorn => "uv add gunicorn",
            Server::RSGI => "",
        }
    }
}

/// Get the appropriate server for an application protocol.
pub fn get_server_type(protocol: AppProtocol) -> Server {
    match protocol {
        AppProtocol::Asgi => Server::Uvicorn,
        AppProtocol::Wsgi => Server::Gunicorn,
        AppProtocol::Unknown => Server::Uvicorn, // Default to uvicorn
    }
}

/// Check if the server is installed
pub fn check_server_installed(server: Server, python_path: &std::path::Path) -> bool {
    use std::process::Command;

    let check_cmd = format!("import {}", server.module_name());
    let mut cmd = Command::new(python_path);
    cmd.args(["-c", &check_cmd]);

    let output = cmd.output();
    output.map(|s| s.status.success()).unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn test_get_server_type_asgi_returns_uvicorn() {
        let server = get_server_type(AppProtocol::Asgi);
        assert_eq!(server, Server::Uvicorn);
    }

    #[test]
    fn test_get_server_type_asgi_returns_uvicorn_again() {
        let server = get_server_type(AppProtocol::Asgi);
        assert_eq!(server, Server::Uvicorn);
    }

    #[test]
    fn test_get_server_type_wsgi_returns_gunicorn() {
        let server = get_server_type(AppProtocol::Wsgi);
        assert_eq!(server, Server::Gunicorn);
    }

    #[test]
    fn test_get_server_type_wsgi_returns_gunicorn_again() {
        let server = get_server_type(AppProtocol::Wsgi);
        assert_eq!(server, Server::Gunicorn);
    }

    #[test]
    fn test_get_server_type_unknown_defaults_to_uvicorn() {
        let server = get_server_type(AppProtocol::Unknown);
        assert_eq!(server, Server::Uvicorn);
    }
}
