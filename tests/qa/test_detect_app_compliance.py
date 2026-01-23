import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# QA: This test validates the interface defined in RFC-0010 §5.2.2
# It acts as a Compliance Suite. If the Dev hasn't implemented it, it fails/skips.

TARGET_MODULE = "python/detect_app.py"


class TestDetectApp(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_dir_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_file(self, filename: str, content: str) -> Path:
        path = self.test_dir_path / filename
        with open(path, "w") as f:
            f.write(content)
        return path

    def run_detection(self, file_path: Path) -> dict[str, Any] | None:
        """Helper to run the detection script via subprocess (Blackbox testing)"""
        script_path = Path(os.getcwd()) / TARGET_MODULE
        if not script_path.exists():
            self.skipTest(f"Developer implementation {TARGET_MODULE} not found")

        # Simulate running: python python/detect_app.py --dir <dir> --output json
        cmd = [
            sys.executable,
            str(script_path),
            "--dir",
            str(file_path.parent),
            "--output",
            "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(result.stdout) if result.returncode == 0 else {}
        except json.JSONDecodeError:
            print(f"Failed to decode JSON: {result.stdout}", file=sys.stderr)
            return None

    def test_flask_app_instance(self):
        self.create_file(
            "main.py",
            """
from flask import Flask
app = Flask(__name__)
""",
        )
        result = self.run_detection(self.test_dir_path / "main.py")
        assert result is not None
        self.assertEqual(result["app"], "app")
        self.assertEqual(result["type"], "Flask")
        # Check POSIX path
        self.assertTrue("/" in result["path"] or "\\\\" not in result["path"])

    def test_django_application(self):
        self.create_file(
            "wsgi.py",
            """
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
application = get_wsgi_application()
""",
        )
        result = self.run_detection(self.test_dir_path / "wsgi.py")
        assert result is not None
        self.assertEqual(result["app"], "application")
        self.assertEqual(result["type"], "Django")

    def test_fastapi_factory(self):
        self.create_file(
            "main.py",
            """
from fastapi import FastAPI

def create_app():
    return FastAPI()
""",
        )
        result = self.run_detection(self.test_dir_path / "main.py")
        assert result is not None
        self.assertEqual(result["app"], "create_app()")
        self.assertEqual(result["type"], "FastAPI")
        self.assertEqual(result["factory"], True)

        # Priority logic test
        res = self.run_detection(self.test_dir_path / "main.py")
        assert res is not None
        # Expect main.py to be picked if passing directory
        # The script should return the ONE best match
        self.assertEqual(res["app"], "create_app()")

    def test_no_app(self):
        self.create_file("utils.py", "def foo(): pass")
        # Passing directory implies scanning
        result = self.run_detection(self.test_dir_path / "utils.py")
        self.assertEqual(result, {})  # Expect empty dict for no match

    def test_syntax_error_resilience(self):
        self.create_file("broken.py", "def foo( This is syntax error")
        result = self.run_detection(self.test_dir_path / "broken.py")
        assert result is not None
        self.assertEqual(result, {})  # Should handle gracefully


if __name__ == "__main__":
    unittest.main()
