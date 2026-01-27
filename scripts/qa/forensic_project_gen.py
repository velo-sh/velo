#!/usr/bin/env python3
"""
Velo Forensic Project Generator (The Science)
Generates high-fidelity, industrial-grade test suites for benchmarking.
"""

import argparse
import shutil
from pathlib import Path


def generate_forensic_project(output_dir: Path, total_tests: int):
    print(f"🧬 Generating Forensic Gold Standard: {output_dir} ({total_tests} tests)")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 1. Infrastructure Setup
    src_root = output_dir / "src" / "velo_app"
    test_root = output_dir / "tests"
    src_root.mkdir(parents=True)
    test_root.mkdir(parents=True)

    # 2. Create Deep Source Hierarchy (4+ levels)
    # Organization: velo_app / {service} / {module} / {submodule} / logic.py
    services = ["auth", "billing", "compute", "storage", "analytics"]

    for service in services:
        svc_path = src_root / service
        svc_path.mkdir(exist_ok=True)
        (svc_path / "__init__.py").write_text("")

        for m in range(2):  # 2 modules per service
            mod_path = svc_path / f"module_{m}"
            mod_path.mkdir(exist_ok=True)
            (mod_path / "__init__.py").write_text("")

            for s in range(2):  # 2 submodules
                sub_path = mod_path / f"sub_{s}"
                sub_path.mkdir(exist_ok=True)
                (sub_path / "__init__.py").write_text("")

                # Logic file with "The Winter" effect (heavy constants)
                logic_file = sub_path / "logic.py"
                logic_file.write_text(f"""
# Forensic Simulation Logic - Layer 4
import math
import os

# Heavy Constant Simulation (Memory Pressure)
HEAVY_REGISTRY = {{f"key_{{i}}": "data" * 50 for i in range(1000)}}

def process_data_{service}_{m}_{s}(x):
    return math.sqrt(x) if x >= 0 else 0
""")

    # 3. Create Test Suite with Deep Import Chains
    # Every test imports from multiple levels to stress the import system
    total_tests // len(services)

    for idx in range(total_tests):
        service = services[idx % len(services)]
        m_idx = (idx // 2) % 2
        s_idx = (idx // 4) % 2

        # Nested test directory mirroring src
        test_dir = test_root / f"layer_1_{service}" / f"layer_2_mod_{m_idx}" / f"layer_3_sub_{s_idx}"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "__init__.py").write_text("")

        test_file = test_dir / f"test_forensic_{idx}.py"

        # The Import Chain stress: import from multiple packages
        test_file.write_text(f"""
import sys
import os
import pytest

# Multi-level Import Stress
from velo_app.{service}.module_{m_idx}.sub_{s_idx} import logic
from velo_app.{services[(idx + 1) % len(services)]}.module_0.sub_0 import logic as cross_logic

def test_forensic_case_{idx}():
    # Simulate realistic work
    res = logic.process_data_{service}_{m_idx}_{s_idx}({idx})
    c_res = cross_logic.process_data_{services[(idx + 1) % len(services)]}_0_0({idx})
    assert res >= 0
    assert c_res >= 0
    assert "velo_app" in sys.modules
""")

    # 4. Add a heavy conftest.py at the root to simulate global setup overhead
    (test_root / "conftest.py").write_text("""
import pytest
import time

@pytest.fixture(scope="session", autouse=True)
def global_setup():
    # Simulate a small global overhead
    # In Velo, this happens once in Zygote
    pass
""")

    print(f"✅ Forensic Project ready at {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()
    generate_forensic_project(Path(args.output), args.count)
