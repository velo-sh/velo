import os
import subprocess
import time

import pytest


def get_zygote_status():
    """Helper to get zygote status via 'velo zygote status'."""
    res = subprocess.run(["./target/debug/velo", "zygote", "status"], capture_output=True, text=True)
    return res.stdout


def get_zygote_pid():
    """Extract PID from status output."""
    status = get_zygote_status()
    for line in status.splitlines():
        if "PID:" in line:
            return int(line.split("PID:")[1].split(")")[0].strip())
    return None


@pytest.fixture(autouse=True)
def cleanup_zygote():
    """Ensure Zygote is stopped before and after each test."""
    subprocess.run(["./target/debug/velo", "zygote", "stop"], capture_output=True)
    time.sleep(0.5)
    yield
    subprocess.run(["./target/debug/velo", "zygote", "stop"], capture_output=True)


@pytest.mark.tier1
def test_guardian_auto_restart():
    """
    Forensic Test: Verify Rust Guardian detects Zygote death and restarts it.
    This is an advanced P1.5 feature that requires further timing refinement.
    """
    # Start Zygote (will start Guardian)
    subprocess.Popen(
        ["./target/debug/velo", "zygote", "start", "--daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(3)  # Give time for startup

    initial_pid = get_zygote_pid()
    assert initial_pid is not None, "Zygote should be running"

    # Kill the Zygote process
    print(f"Killing Zygote PID {initial_pid}...")
    os.kill(initial_pid, 9)

    # Wait for Guardian to detect death (interval is 5s) + restart + startup
    print("Waiting for Guardian to perform emergency restart...")
    start_wait = time.time()
    restarted_pid = None
    while (time.time() - start_wait) < 20:
        time.sleep(1)
        restarted_pid = get_zygote_pid()
        if restarted_pid and restarted_pid != initial_pid:
            break

    assert restarted_pid is not None, "Zygote should have been restarted"
    assert restarted_pid != initial_pid, "Restarted PID should be different"
    print(f"✅ Guardian successfully performed resurrection. New PID: {restarted_pid}")


@pytest.mark.tier0
def test_guardian_basic_health_check():
    """
    Verify the Guardian starts successfully and Zygote reports health metrics.
    """
    subprocess.Popen(
        ["./target/debug/velo", "zygote", "start", "--daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(3)

    status = get_zygote_status()
    assert "Running ✅" in status, f"Zygote should be running. Got: {status}"

    pid = get_zygote_pid()
    assert pid is not None, "Should be able to extract PID from status"
