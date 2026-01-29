#!/usr/bin/env python3
import os
import sys
import socket
import struct
import json
import importlib
import signal
import traceback

PROTOCOL_VERSION = 1

class IdlePool:
    def __init__(self, target_size=0):
        self.target_size = target_size
        self.pool = [] # List of (pid, pipe_write_fd)
    
    def get_count(self):
        self.pool = [p for p in self.pool if self._is_alive(p[0])]
        return len(self.pool)
    
    def _is_alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
            
    def add(self, pid, pipe_write_fd):
        self.pool.append((pid, pipe_write_fd))
        
    def pop(self):
        while self.pool:
            pid, write_fd = self.pool.pop(0)
            if self._is_alive(pid):
                return pid, write_fd
            try: os.close(write_fd)
            except: pass
        return None, None

    def replenish(self, main_sock=None):
        current = self.get_count()
        while current < self.target_size:
            r_fd, w_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                # --- POOLED WORKER ---
                os.close(w_fd)
                if main_sock:
                    try: main_sock.close()
                    except: pass
                # Reset signals in child
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                self._worker_loop(r_fd)
                sys.exit(0)
            else:
                os.close(r_fd)
                self.add(pid, w_fd)
                current += 1

    def _worker_loop(self, pipe_read_fd):
        try:
            header = os.read(pipe_read_fd, 4)
            if not header: return
            length = struct.unpack("<I", header)[0]
            payload = b""
            while len(payload) < length:
                chunk = os.read(pipe_read_fd, length - len(payload))
                if not chunk: break
                payload += chunk
            msg = json.loads(payload.decode('utf-8'))
            execute_payload(msg)
        except Exception as e:
            traceback.print_exc()
        finally:
            os.close(pipe_read_fd)

def execute_payload(msg):
    app_module = msg.get("module")
    script_path = msg.get("script_path")
    env_overrides = msg.get("env", {})
    if env_overrides:
        os.environ.update(env_overrides)

    if app_module:
        if ":" in app_module:
            mod_name, obj_name = app_module.split(":")
            mod = importlib.import_module(mod_name)
            app = getattr(mod, obj_name)
        else:
            importlib.import_module(app_module)
    elif script_path:
        with open(script_path, "rb") as f:
            code = compile(f.read(), script_path, "exec")
            exec(code, {"__name__": "__main__"})

IDLE_POOL = IdlePool()

def bootstrap():
    socket_path = os.environ.get("VELO_ZYGOTE_SOCK")
    if not socket_path:
        sys.exit(1)
    
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    
    # Send Ready
    payload = json.dumps({"type": "Ready"}).encode('utf-8')
    total_len = 1 + len(payload)
    sock.sendall(struct.pack("<I", total_len) + struct.pack("B", PROTOCOL_VERSION) + payload)

    while True:
        try:
            raw_len = sock.recv(4)
            if not raw_len: break
            total_len = struct.unpack("<I", raw_len)[0]
            v_buf = sock.recv(1)
            if not v_buf: break
            payload = sock.recv(total_len - 1).decode('utf-8')
            msg = json.loads(payload)
            
            cmd = msg.get("type")
            if cmd == "Auth":
                resp = {"type": "Ack"}
            elif cmd == "Handshake":
                resp = {"type": "Handshake", "version": PROTOCOL_VERSION, "capabilities": ["v3-shim", "pool"]}
            elif cmd == "Status":
                resp = {
                    "type": "Status",
                    "pid": os.getpid(),
                    "preload": [],
                    "state": "READY",
                    "preload_done": True,
                    "pool_count": IDLE_POOL.get_count(),
                    "target_pool_size": IDLE_POOL.target_size
                }
            elif cmd == "ReplenishPool":
                IDLE_POOL.target_size = msg.get("target_count", 0)
                IDLE_POOL.replenish(main_sock=sock)
                resp = {"type": "Ack"}
            elif cmd == "Fork":
                pid, pipe_fd = IDLE_POOL.pop()
                if pid:
                    p = json.dumps(msg).encode('utf-8')
                    os.write(pipe_fd, struct.pack("<I", len(p)) + p)
                    os.close(pipe_fd)
                    resp = {"type": "Forked", "worker_pid": pid, "is_warm": True}
                    # Replenish after assignment
                    IDLE_POOL.replenish(main_sock=sock)
                else:
                    pid = os.fork()
                    if pid == 0:
                        sock.close()
                        execute_payload(msg)
                        sys.exit(0)
                    resp = {"type": "Forked", "worker_pid": pid, "is_warm": False}
            elif cmd == "Exit" or cmd == "Shutdown":
                break
            else:
                resp = {"type": "Ack"}
            
            p = json.dumps(resp).encode('utf-8')
            sock.sendall(struct.pack("<I", 1 + len(p)) + struct.pack("B", PROTOCOL_VERSION) + p)
        except Exception as e:
            break

if __name__ == "__main__":
    bootstrap()
