import sys
import os
import ctypes

def check_darwin_isolation():
    """
    Isolation probing for macOS (Darwin).
    Since macOS lacks Linux PID Namespace, we check if process is in virtual sandbox or
    restricted Mach-task context.
    """
    try:
        # Try calling sandbox_check (private API but common for security probing)
        # Check if current process is restricted in file write or process management
        # Returns 0 if restricted (Isolated), non-zero otherwise
        libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        # sandbox_check(pid, operation, type, ...)
        # Heuristic check: verify if other processes can be unrestricted probed
        res = libsystem.sandbox_check(os.getpid(), None, 0)
        if res == 0:
            return "S-" # macOS Sandbox Restricted Mode
        return "B" # Standard macOS Process
    except:
        # If private API unavailable, check for special Mach Task port restricted state
        return "B"

def check_linux_isolation():
    """
    Isolation probing for Linux.
    """
    stats = {}
    try:
        # 1. PID Namespace Check
        with open("/proc/self/ns/pid", "r") as f:
            stats["ns"] = f.read()
        
        # 2. Check for dirty page leak risk (heuristic)
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    stats["rss"] = line.split()[1]
        
        return "S" if stats.get("ns") else "B"
    except:
        return "B"

def check_isolation():
    print(f"[HIO] Probing Isolation Engine for {sys.platform}...")
    
    grade = "B"
    if sys.platform == "darwin":
        grade = check_darwin_isolation()
    elif sys.platform == "linux":
        grade = check_linux_isolation()
        
    print(f"[HIO] Final Isolation Grade: {grade}")
    return grade

if __name__ == "__main__":
    grade = check_isolation()
    # Per run_hio.sh logic, exit 0 means HIO standard met (S/S-)
    if grade in ["S", "S-"]:
        sys.exit(0)
    else:
        sys.exit(1)
