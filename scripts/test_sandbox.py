import os
import subprocess
import tempfile

def test_sandbox():
    cwd = os.getcwd()
    profile = f"""(version 1)
(allow default)
(allow file-read*)
(deny file-write*
    (subpath "/Users")
)
(allow file-write*
    (subpath "{cwd}")
)
"""
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(profile)
        profile_path = f.name

    print(f"Testing sandbox profile:\n{profile}")
    
    try:
        # Try to write to a file in CWD using sandbox-exec
        cmd = ["sandbox-exec", "-p", open(profile_path).read(), "touch", "sandbox_test_file"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ SUCCEEDED: Write allowed (Allow rule matched or Deny ignored)")
            if os.path.exists("sandbox_test_file"):
                os.remove("sandbox_test_file")
        else:
            print(f"❌ FAILED: Write denied. Exit code {result.returncode}")
            print("Stderr:", result.stderr)

    finally:
        os.remove(profile_path)

if __name__ == "__main__":
    test_sandbox()
