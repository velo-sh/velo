#!/usr/bin/env python3
# bootstrap.py - Velo V3 Zero-Dependency Shim (RFC-0012)
#
# This script is the first code executed in the Zygote process tree.
# It is designed to be lean, zero-dependency, and high-performance.

import os
import sys
import socket
import struct
import json
import importlib
import signal
import traceback

PROTOCOL_VERSION = 1

def bootstrap():
    # 1. Identity Verification
    # Supervisor passed config via stdin or env
    socket_path = os.environ.get("VELO_ZYGOTE_SOCK")
    if not socket_path:
        print("🚨 [BOOTSTRAP] Error: VELO_ZYGOTE_SOCK not set.", file=sys.stderr)
        sys.exit(1)
    
    print(f"🔗 [BOOTSTRAP] Attempting to connect to: {socket_path}", file=sys.stderr)

    # 2. Connect to Supervisor (with retries for race conditions)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    retries = 10
    connected = False
    while retries > 0:
        try:
            sock.connect(socket_path)
            connected = True
            break
        except Exception as e:
            retries -= 1
            if retries == 0:
                print(f"🚨 [BOOTSTRAP] Connection failed after retries: {e}", file=sys.stderr)
                sys.exit(1)
            import time
            time.sleep(0.1)

    print(f"⚡ [BOOTSTRAP] Connected to Supervisor at {socket_path}", file=sys.stderr)

    # 3. Proactive Initialization (RFC-0012 §3.1)
    # If VIRTUAL_ENV is passed in, inject it immediately before sending Ready
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        import site
        # Dynamic site-packages resolution
        site_pkgs = os.path.join(venv, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
        if os.path.exists(site_pkgs):
            site.addsitedir(site_pkgs)
            print(f"💉 [BOOTSTRAP] Proactive Injection: {site_pkgs}", file=sys.stderr)
        
        # Also inject current directory into sys.path[0] for source loading
        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

    # Send Ready greeting (Framing: LE 4B Length, 1B Version, Payload)
    send_response(sock, {"type": "Ready"})

    # 4. Main Command Loop
    while True:
        try:
            # Read 4-byte length prefix (Little-Endian)
            raw_len = sock.recv(4)
            if not raw_len:
                break
            total_len = struct.unpack("<I", raw_len)[0]
            
            # Read version byte
            version = sock.recv(1)[0]
            if version != PROTOCOL_VERSION:
                print(f"🚨 [BOOTSTRAP] Version mismatch: got {version}, expected {PROTOCOL_VERSION}", file=sys.stderr)
                break
            
            # Read message content
            payload_len = total_len - 1
            payload = sock.recv(payload_len).decode('utf-8')
            msg = json.loads(payload)
            
            cmd = msg.get("type") # ZygoteCommand uses 'type' tag
            if cmd == "Auth":
                # SEC-005: Ack auth immediately for now (or implement logic)
                send_response(sock, {"type": "Ack"})
            elif cmd == "Handshake":
                send_response(sock, {
                    "type": "Handshake",
                    "version": PROTOCOL_VERSION,
                    "capabilities": ["v3-shim"]
                })
            elif cmd == "Status":
                send_response(sock, {
                    "type": "Status",
                    "pid": os.getpid(),
                    "preload": [],
                    "state": "READY",
                    "preload_done": True,
                    "pool_count": 0,
                    "target_pool_size": 0
                })
            elif cmd == "Fork":
                handle_fork(sock, msg)
            elif cmd == "Exit":
                break
        except Exception as e:
            print(f"⚠️ [BOOTSTRAP] Error in loop: {e}", file=sys.stderr)
            traceback.print_exc()
            break

def handle_fork(sock, msg):
    """Forks a worker process."""
    # In ZygoteCommand::Fork, the module name is in msg.get("module")
    # or the script_path is in msg.get("script_path")
    app_module = msg.get("module")
    script_path = msg.get("script_path")
    
    pid = os.fork()
    if pid == 0:
        # --- CHILD WORKER ---
        try:
            sock.close()
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

            if app_module:
                print(f"🚀 [WORKER] Loading module {app_module}...", file=sys.stderr)
                # module_name:object_name (e.g. main:app)
                if ":" in app_module:
                    mod_name, obj_name = app_module.split(":")
                    mod = importlib.import_module(mod_name)
                    app = getattr(mod, obj_name)
                else:
                    importlib.import_module(app_module)
            elif script_path:
                print(f"🚀 [WORKER] Running script {script_path}...", file=sys.stderr)
                # Execute script
                with open(script_path, "rb") as f:
                    code = compile(f.read(), script_path, "exec")
                    exec(code, {"__name__": "__main__"})
            
            sys.exit(0)
        except Exception as e:
            print(f"🚨 [WORKER] Failed: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
    else:
        # --- PARENT ZYGOTE ---
        send_response(sock, {"type": "Forked", "worker_pid": pid})

def send_response(sock, data):
    payload = json.dumps(data).encode('utf-8')
    total_len = 1 + len(payload)
    header = struct.pack("<I", total_len)
    version = struct.pack("B", PROTOCOL_VERSION)
    sock.sendall(header + version + payload)


if __name__ == "__main__":
    bootstrap()
