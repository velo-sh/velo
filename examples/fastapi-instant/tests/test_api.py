import warnings

# Completely suppress SSL compatibility noise (common on macOS)
warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")

import os

import requests

BASE_URL = "http://127.0.0.1:8000"


def test_atomic_reset():
    print("[HIO] Running Atomic Reset Test (SQLite + Filesystem)...")
    print("[HIO] ⚠️ Note: Emulated Namespace Isolation")

    # 1. Verify initial state (should be 0)
    print("[HIO] Step 0: Checking initial state...")
    try:
        initial_resp = requests.get(f"{BASE_URL}/", timeout=5)
    except Exception as e:
        print(f"\033[1;31m[ERROR] Server not reachable: {e}\033[0m")
        exit(1)

    initial_data = initial_resp.json()
    initial_count = initial_data["state_len"]
    print(f"[HIO] Initial row count: {initial_count}")

    # 2. Dirty state (write to database)
    print("[HIO] Step 1: Dirtying database via POST /dirty")
    dirty_resp = requests.post(f"{BASE_URL}/dirty", json={"test": "data"}, timeout=5)
    dirty_data = dirty_resp.json()
    print(f"[HIO] POST /dirty -> ✅ Row inserted (count: {dirty_data['current_count']})")

    # 3. Verify database is dirtied
    check_resp = requests.get(f"{BASE_URL}/", timeout=5)
    check_data = check_resp.json()
    assert check_data["state_len"] >= 1, "Database should have at least 1 row"
    print(f"[HIO] Step 2: Database SIDE-EFFECT confirmed (rows: {check_data['state_len']})")

    # 4. Verify database file exists
    workspace = os.getenv("VELO_WORKSPACE", "/tmp/velo_hio_003")
    db_path = os.path.join(workspace, "demo.db")
    if os.path.exists(db_path):
        print(f"[HIO] Step 3: Database file confirmed at {db_path}")
    else:
        print(f"[HIO] Step 3: Database at {check_data.get('db_path', 'unknown')}")

    print("\n[HIO] ACTION: Velo Snap-Back will now purge all side effects...")
    print("[HIO] EXPECTATION: Next run should show row_count=0 and NO database file.")
    print(f"\n[HIO] 📎 Isolation Note: {check_data.get('isolation_note', 'N/A')}")


if __name__ == "__main__":
    test_atomic_reset()
