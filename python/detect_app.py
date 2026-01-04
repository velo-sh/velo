#!/usr/bin/env python3
"""
Velo App Detection - AST-based ASGI/WSGI app discovery

RFC-0010 §5.2.2: Uses Python's ast module for reliable app detection.

Usage:
    python detect_app.py [--dir PATH] [--output json|simple]

Output formats:
    simple: module:app (e.g., "main:app")
    json:   {"module": "main", "app": "app", "type": "FastAPI", "factory": false}
"""

import ast
import json
import sys
from pathlib import Path
from typing import Optional, NamedTuple, List


class AppInfo(NamedTuple):
    """Detected application information."""
    module: str          # Module path (e.g., "main" or "myapp.main")
    app: str             # App variable name (e.g., "app" or "application")
    framework: str       # Framework type (FastAPI, Flask, Django, Starlette, Unknown)
    factory: bool        # True if factory pattern (e.g., create_app())
    path: Path           # Absolute path to the file


# Framework patterns: (call_name, framework_type)
FRAMEWORK_PATTERNS = [
    ("FastAPI", "FastAPI"),
    ("Flask", "Flask"),
    ("Starlette", "Starlette"),
    ("Django", "Django"),
    ("Sanic", "Sanic"),
    ("Quart", "Quart"),
    ("get_wsgi_application", "Django"),
    ("get_asgi_application", "Django"),
]

# Factory function patterns
FACTORY_PATTERNS = [
    "create_app",
    "make_app",
    "app_factory",
    "get_app",
    "get_application",
]


class AppDetector(ast.NodeVisitor):
    """AST visitor for detecting ASGI/WSGI app definitions."""
    
    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.apps = [] # type: List[AppInfo]
        self.factories = [] # type: List[AppInfo]
        self._current_function = None # type: Optional[str]
    
    def visit_Assign(self, node: ast.Assign) -> None:
        """Detect: app = FastAPI() or application = Flask(__name__)"""
        if not isinstance(node.value, ast.Call):
            self.generic_visit(node)
            return
        
        # Get the call name
        call_name = self._get_call_name(node.value)
        if not call_name:
            self.generic_visit(node)
            return
        
        # Check if it's a known framework
        framework = self._match_framework(call_name)
        if not framework:
            self.generic_visit(node)
            return
        
        # Get assigned variable name
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.apps.append(AppInfo(
                    module=self._get_module_path(),
                    app=target.id,
                    framework=framework,
                    factory=False,
                    path=self.source_path,
                ))
        
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Detect factory pattern: def create_app() -> FastAPI: ..."""
        # Check if function name matches factory patterns
        if node.name not in FACTORY_PATTERNS:
            self.generic_visit(node)
            return
        
        # Check return annotation
        framework = None
        if node.returns:
            if isinstance(node.returns, ast.Name):
                framework = self._match_framework(node.returns.id)
            elif isinstance(node.returns, ast.Constant):
                framework = self._match_framework(str(node.returns.value))
        
        # Check for return statement with framework call
        if not framework:
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                    call_name = self._get_call_name(stmt.value)
                    if call_name:
                        framework = self._match_framework(call_name)
                        if framework:
                            break
        
        if framework:
            self.factories.append(AppInfo(
                module=self._get_module_path(),
                app=f"{node.name}()",
                framework=framework,
                factory=True,
                path=self.source_path,
            ))
        
        self.generic_visit(node)
    
    # Also catch async factory functions
    visit_AsyncFunctionDef = visit_FunctionDef
    
    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Extract the name of a function call."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None
    
    def _match_framework(self, name: str) -> Optional[str]:
        """Match a name to a known framework."""
        for pattern, framework in FRAMEWORK_PATTERNS:
            if name == pattern:
                return framework
        return None
    
    def _get_module_path(self) -> str:
        """Get the module path relative to the scan directory (POSIX style)."""
        # scan_dir is set in main and passed here? No, I need to pass it or use CWD
        # For simplicity, use relative path if possible
        try:
            rel_path = self.source_path.relative_to(Path.cwd()).with_suffix("")
            return str(rel_path.as_posix()).replace("/", ".")
        except ValueError:
            # Fallback to absolute if not relative to CWD
            return self.source_path.stem


def detect_app_in_file(file_path: Path) -> List[AppInfo]:
    """Detect ASGI/WSGI apps in a single Python file."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    
    detector = AppDetector(file_path)
    detector.visit(tree)
    
    # Prefer regular apps over factories
    return detector.apps if detector.apps else detector.factories


def detect_all_apps_in_directory(directory: Path) -> List[AppInfo]:
    """
    Detect all potential ASGI/WSGI apps in a directory.
    """
    all_apps = []
    
    # Priority files list
    priority_files = ["main.py", "app.py", "application.py", "wsgi.py", "asgi.py"]
    
    # Scan all .py files in the directory
    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        apps = detect_app_in_file(py_file)
        if apps:
            all_apps.extend(apps)
            
    # Sort so priority files come first
    all_apps.sort(key=lambda x: (0 if x.path.name in priority_files else 1, x.path.name))
    
    return all_apps


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Detect ASGI/WSGI app")
    parser.add_argument("--dir", "-d", type=Path, default=Path.cwd(),
                        help="Directory to scan (default: current)")
    parser.add_argument("--output", "-o", choices=["simple", "json"], default="simple",
                        help="Output format")
    
    args = parser.parse_args()
    
    apps = detect_all_apps_in_directory(args.dir.resolve())
    
    if not apps:
        print("error: No ASGI/WSGI app detected", file=sys.stderr)
        sys.exit(1)
    
    if args.output == "json":
        # Return all found apps in JSON
        results = []
        for app in apps:
            results.append({
                "module": app.module,
                "app": app.app,
                "type": app.framework,
                "factory": app.factory,
                "path": str(app.path.as_posix()),
            })
        print(json.dumps(results))
    else:
        # Simple format: just the first one module:app
        print(f"{apps[0].module}:{apps[0].app}")


if __name__ == "__main__":
    main()
