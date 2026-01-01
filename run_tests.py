import subprocess
import sys
import time
from pathlib import Path


VELO_BIN = "./target/release/velo"
CORPUS_DIR = Path("./tests/corpus")

def compile_velo():
    print("🔨 Building Velo...", end="", flush=True)
    res = subprocess.run(["cargo", "build", "--release"], capture_output=True)
    if res.returncode != 0:
        print("\n❌ Build Failed!")
        print(res.stderr.decode())
        sys.exit(1)
    print(" ✅ Done.")

def run_case(script_path):
    print(f"🧪 Testing {script_path.name}...", end="", flush=True)
    
    start = time.time()
    res_py = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    time_py = time.time() - start

    start = time.time()
    res_velo = subprocess.run([VELO_BIN, "run", str(script_path)], capture_output=True, text=True)
    time_velo = time.time() - start

    if res_py.returncode != res_velo.returncode:
        print(f" ❌ Return Code Mismatch! (Py={res_py.returncode}, Velo={res_velo.returncode})")
        return False
        
    if res_py.stdout.strip() != res_velo.stdout.strip():
        print(f" ❌ Output Mismatch!")
        print(f"Expect: {res_py.stdout.strip()}")
        print(f"Actual: {res_velo.stdout.strip()}")
        return False

    print(f" ✅ PASS | Py: {time_py:.4f}s vs Velo: {time_velo:.4f}s")
    return True

if __name__ == "__main__":
    compile_velo()
    
    passed = True
    test_files = list(CORPUS_DIR.glob("*.py"))
    
    if not test_files:
        print("⚠️  No tests found in tests/corpus/")
        
    for script in test_files:
        if not run_case(script):
            passed = False
            
    if not passed:
        sys.exit(1)
    print("\n✨ All Systems Operational.")