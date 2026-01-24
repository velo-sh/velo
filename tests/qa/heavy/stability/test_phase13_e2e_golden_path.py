"""
RFC-0028 Phase 13: E2E Golden Path Test

This is the V1 COMPLETION CRITERIA test.
It covers the longest happy path with a real FastAPI test scenario.

Test Flow:
1. Create a FastAPI app with multiple endpoints
2. Create pytest tests for the app
3. Run tests via `velo test`
4. Verify all tests pass
5. Verify exit code is 0

This proves the full integration from CLI → pytest → execution → results.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fastapi_test_project():
    """
    Create a complete FastAPI test project with:
    - app.py: FastAPI app with multiple endpoints
    - test_app.py: pytest tests for the app
    - conftest.py: fixtures
    """
    project_dir = tempfile.mkdtemp(prefix="velo_e2e_fastapi_")

    # Create FastAPI app
    app_code = '''
"""Sample FastAPI app for E2E testing"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Velo E2E Test App")

# In-memory database
items_db: dict[int, dict] = {}
next_id: int = 1


class Item(BaseModel):
    name: str
    price: float
    description: str = ""


class ItemResponse(BaseModel):
    id: int
    name: str
    price: float
    description: str


@app.get("/")
def read_root():
    return {"message": "Hello from Velo E2E test"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.post("/items", response_model=ItemResponse)
def create_item(item: Item):
    global next_id
    item_id = next_id
    next_id += 1
    items_db[item_id] = {
        "id": item_id,
        "name": item.name,
        "price": item.price,
        "description": item.description,
    }
    return items_db[item_id]


@app.get("/items/{item_id}", response_model=ItemResponse)
def read_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return items_db[item_id]


@app.get("/items")
def list_items():
    return list(items_db.values())


@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    del items_db[item_id]
    return {"deleted": item_id}
'''

    # Create test file
    test_code = '''
"""Tests for the FastAPI app"""
import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app"""
    return TestClient(app)


class TestHealthEndpoints:
    """Health check endpoint tests"""

    def test_root_endpoint(self, client):
        """Test the root endpoint returns hello message"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "Hello" in data["message"]

    def test_health_check(self, client):
        """Test health endpoint returns healthy status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestItemsCRUD:
    """Full CRUD operations on items"""

    def test_create_item(self, client):
        """Test creating a new item"""
        item_data = {
            "name": "Test Widget",
            "price": 29.99,
            "description": "A test widget for E2E testing"
        }
        response = client.post("/items", json=item_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == item_data["name"]
        assert data["price"] == item_data["price"]
        assert "id" in data

    def test_read_item(self, client):
        """Test reading an item by ID"""
        # Create an item first
        item_data = {"name": "Read Test", "price": 10.0}
        create_resp = client.post("/items", json=item_data)
        item_id = create_resp.json()["id"]

        # Read it back
        response = client.get(f"/items/{item_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == item_id
        assert data["name"] == "Read Test"

    def test_list_items(self, client):
        """Test listing all items"""
        # Create a couple of items
        client.post("/items", json={"name": "Item A", "price": 5.0})
        client.post("/items", json={"name": "Item B", "price": 10.0})

        response = client.get("/items")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_delete_item(self, client):
        """Test deleting an item"""
        # Create an item
        create_resp = client.post("/items", json={"name": "To Delete", "price": 1.0})
        item_id = create_resp.json()["id"]

        # Delete it
        response = client.delete(f"/items/{item_id}")
        assert response.status_code == 200
        assert response.json()["deleted"] == item_id

        # Verify it's gone
        get_resp = client.get(f"/items/{item_id}")
        assert get_resp.status_code == 404

    def test_item_not_found(self, client):
        """Test 404 error for non-existent item"""
        response = client.get("/items/999999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestComplexScenarios:
    """Complex scenarios covering edge cases"""

    def test_full_lifecycle(self, client):
        """Test full item lifecycle: create -> read -> update -> delete"""
        # Create
        item_data = {"name": "Lifecycle Item", "price": 100.0, "description": "Full test"}
        create_resp = client.post("/items", json=item_data)
        assert create_resp.status_code == 200
        item_id = create_resp.json()["id"]

        # Read
        read_resp = client.get(f"/items/{item_id}")
        assert read_resp.status_code == 200
        assert read_resp.json()["name"] == "Lifecycle Item"

        # List (should contain our item)
        list_resp = client.get("/items")
        item_ids = [item["id"] for item in list_resp.json()]
        assert item_id in item_ids

        # Delete
        delete_resp = client.delete(f"/items/{item_id}")
        assert delete_resp.status_code == 200

        # Verify deleted
        verify_resp = client.get(f"/items/{item_id}")
        assert verify_resp.status_code == 404

    def test_multiple_items_creation(self, client):
        """Test creating multiple items in sequence"""
        items_created = []
        for i in range(5):
            resp = client.post("/items", json={
                "name": f"Bulk Item {i}",
                "price": float(i * 10),
            })
            assert resp.status_code == 200
            items_created.append(resp.json()["id"])

        # Verify all items exist
        for item_id in items_created:
            resp = client.get(f"/items/{item_id}")
            assert resp.status_code == 200
'''

    # Create conftest.py
    conftest_code = '''
"""Pytest configuration for E2E tests"""
import pytest

# Ensure proper asyncio handling
pytest_plugins = ["pytest_asyncio"]
'''

    # Write files
    (Path(project_dir) / "app.py").write_text(app_code)
    (Path(project_dir) / "test_app.py").write_text(test_code)
    (Path(project_dir) / "conftest.py").write_text(conftest_code)

    yield project_dir

    # Cleanup
    shutil.rmtree(project_dir, ignore_errors=True)


class TestE2EGoldenPath:
    """
    E2E Golden Path Tests - V1 Completion Criteria

    This class contains tests that prove velo test works end-to-end
    with a real-world FastAPI project.
    """

    def test_e2e_velo_test_fastapi_project(self, fastapi_test_project):
        """
        GOLDEN PATH TEST: Run velo test on a real FastAPI project

        This is the PRIMARY V1 completion criteria.
        If this test passes, the velo test feature is working.
        """
        project_dir = fastapi_test_project
        velo_root = Path(__file__).parents[4]

        result = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                "test_app.py",
                "-v",
            ],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=60,
            env={
                **os.environ,
                "PYTHONPATH": project_dir,
            },
        )

        # Print output for debugging
        print("=== STDOUT ===")
        print(result.stdout)
        print("=== STDERR ===")
        print(result.stderr)

        # FAIL FAST: Check for missing dependency errors first
        if "ModuleNotFoundError" in result.stdout or "ImportError" in result.stdout:
            missing_module = None
            for line in result.stdout.split("\n"):
                if "No module named" in line:
                    # Extract module name from: ModuleNotFoundError: No module named 'xxx'
                    import re

                    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", line)
                    if match:
                        missing_module = match.group(1)
                        break
            pytest.fail(
                f"FAIL FAST: Missing dependency detected: {missing_module or 'unknown'}\n"
                f"Fix: uv pip install {missing_module or '<module>'}\n"
                f"Exit code was: {result.returncode}"
            )

        # Verify all tests passed
        assert result.returncode == 0, f"velo test failed with exit code {result.returncode}"
        assert "passed" in result.stdout.lower(), "Expected 'passed' in output"
        assert "failed" not in result.stdout.lower() or "0 failed" in result.stdout.lower()

    def test_e2e_test_count_verification(self, fastapi_test_project):
        """
        Verify that all expected tests are discovered and run

        Expected tests:
        - 2 health endpoint tests
        - 5 CRUD tests
        - 2 complex scenario tests
        = 9 tests total
        """
        project_dir = fastapi_test_project
        velo_root = Path(__file__).parents[4]

        result = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                "test_app.py",
                "-v",
            ],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=60,
            env={
                **os.environ,
                "PYTHONPATH": project_dir,
            },
        )

        # Check that we ran the expected number of tests
        # Look for "X passed" in output
        import re

        match = re.search(r"(\d+) passed", result.stdout)
        assert match, "Could not find 'X passed' in output"
        passed_count = int(match.group(1))
        assert passed_count >= 9, f"Expected at least 9 tests, got {passed_count}"

    def test_e2e_exit_code_propagation(self, fastapi_test_project):
        """
        Verify that exit codes are properly propagated

        - Success: exit code 0
        - Failure: exit code 1
        """
        project_dir = fastapi_test_project
        velo_root = Path(__file__).parents[4]

        # Create a failing test
        failing_test = """
def test_intentional_failure():
    assert False, "This test should fail"
"""
        failing_test_path = Path(project_dir) / "test_failing.py"
        failing_test_path.write_text(failing_test)

        result = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                "test_failing.py",
            ],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=30,
        )

        # Failing test should return exit code 1
        assert result.returncode == 1, "Failing test should return exit code 1"

        # Clean test should return exit code 0
        result_clean = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                "test_app.py",
            ],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=60,
            env={
                **os.environ,
                "PYTHONPATH": project_dir,
            },
        )
        assert result_clean.returncode == 0, "Passing tests should return exit code 0"


class TestE2EFailFast:
    """
    Fail-Fast Tests - Verify immediate failure on missing dependencies

    These tests ensure velo test fails fast with clear error messages
    when dependencies are missing, rather than hanging or timing out.
    """

    def test_missing_package_fails_fast(self, tmp_path):
        """
        Test that importing a non-existent package fails immediately
        with a clear ModuleNotFoundError, not a hang or timeout.
        """
        velo_root = Path(__file__).parents[4]

        # Create test file that imports a non-existent package
        test_file = tmp_path / "test_missing_dep.py"
        test_file.write_text('''
"""Test file that imports a non-existent package"""
import nonexistent_package_xyz_12345  # This package does not exist

def test_should_not_run():
    """This test should never execute because import fails"""
    assert True
''')

        result = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                str(test_file),
            ],
            capture_output=True,
            text=True,
            timeout=10,  # Should fail MUCH faster than 10 seconds
        )

        # Verify fail-fast behavior
        assert result.returncode != 0, "Should fail with non-zero exit code"
        assert "ModuleNotFoundError" in result.stdout or "No module named" in result.stdout, (
            f"Should show clear ModuleNotFoundError in output: {result.stdout}"
        )
        assert "nonexistent_package_xyz_12345" in result.stdout, "Should show the missing package name"

    def test_missing_package_execution_time(self, tmp_path):
        """
        Verify that missing package error is detected quickly (< 5 seconds)
        """
        import time

        velo_root = Path(__file__).parents[4]

        test_file = tmp_path / "test_missing_quick.py"
        test_file.write_text("""
import some_fake_module_that_does_not_exist

def test_never_runs():
    pass
""")

        start = time.time()
        result = subprocess.run(
            [
                str(velo_root / "target/release/velo"),
                "test",
                str(test_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed = time.time() - start

        # Should fail fast, not hang
        assert elapsed < 5.0, f"Fail-fast took {elapsed:.1f}s, expected < 5s"
        assert result.returncode != 0
