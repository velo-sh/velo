import os
import subprocess


def test_DEF_08_006_benchmark_shadowing_reproduction():
    """
    REPRODUCTION for DEF-08-006:
    Demonstrates that having multiple benchmark tiers' 'src' directories in PYTHONPATH
    causes package shadowing preventng some tests from finding their 'velo_app'.
    """
    root = os.getcwd()
    gold100_src = os.path.join(root, "tests/qa/forensic_benchmarks/gold_100/src")
    gold200_src = os.path.join(root, "tests/qa/forensic_benchmarks/gold_200/src")

    # Tier 1 analytics module in gold_100
    test_file_100 = (
        "tests/qa/forensic_benchmarks/gold_100/tests/layer_1_analytics/layer_2_mod_1/layer_3_sub_0/test_forensic_19.py"
    )
    # Tier 1 analytics module in gold_200
    test_file_200 = (
        "tests/qa/forensic_benchmarks/gold_200/tests/layer_1_analytics/layer_2_mod_0/layer_3_sub_0/test_forensic_4.py"
    )

    # CASE A: Run gold_100 test with both in path
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{gold100_src}:{gold200_src}"

    print("\n--- Running gold_100 test with both sources in PYTHONPATH ---")
    res1 = subprocess.run(["uv", "run", "pytest", test_file_100, "-v"], env=env, capture_output=True, text=True)
    print(f"Result (Exit code {res1.returncode})")
    if res1.returncode != 0:
        print("FAILED as expected: Shadowing or path conflict detected.")
    else:
        print("PASSED: No conflict (or Python picked the right one by chance)")

    # CASE B: Run gold_200 test with both in path
    print("\n--- Running gold_200 test with both sources in PYTHONPATH ---")
    res2 = subprocess.run(["uv", "run", "pytest", test_file_200, "-v"], env=env, capture_output=True, text=True)
    print(f"Result (Exit code {res2.returncode})")

    # Analysis
    assert res1.returncode != 0 or res2.returncode != 0, (
        "Suite collision not reproduced. Both tests passed despite overlapping namespaces."
    )

    if (
        "ModuleNotFoundError: No module named 'velo_app'" in res1.stderr
        or "ModuleNotFoundError: No module named 'velo_app'" in res2.stderr
    ):
        print("\nCONFIRMED: 'ModuleNotFoundError: No module named velo_app' triggered by environment pollution.")


if __name__ == "__main__":
    test_DEF_08_006_benchmark_shadowing_reproduction()
