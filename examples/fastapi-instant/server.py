from fastapi import FastAPI, Request
import os
import sqlite3
import tempfile

try:
    import psutil
except ImportError:
    psutil = None

app = FastAPI()

# Use private temporary directory for isolation
WORKSPACE = os.getenv("VELO_WORKSPACE", tempfile.mkdtemp(prefix="velo_hio_"))
os.makedirs(WORKSPACE, exist_ok=True)
DB_PATH = os.path.join(WORKSPACE, "demo.db")

def init_db():
    """Initialize SQLite Database"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS side_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_row_count() -> int:
    """Get database row count"""
    if not os.path.exists(DB_PATH):
        return 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM side_effects")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Initialize database on startup
init_db()

@app.get("/")
async def get_state():
    mem_info = psutil.Process().memory_info().rss if psutil else 0
    row_count = get_row_count()
    return {
        "state_len": row_count,
        "pid": os.getpid(),
        "memory_info": mem_info,
        "workspace": WORKSPACE,
        "db_path": DB_PATH,
        "isolation_note": "Emulated Namespace Isolation"
    }

@app.post("/dirty")
async def dirty_state(request: Request):
    """
    Create memory and database side effects
    """
    import json
    payload = await request.json()
    
    # Database side effect
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO side_effects (data) VALUES (?)", [json.dumps(payload)])
    conn.commit()
    conn.close()
    
    row_count = get_row_count()
    print(f"[HIO] POST /dirty -> ✅ Row inserted into demo.db (count: {row_count})")
    
    return {"status": "Dirtied", "current_count": row_count, "db_path": DB_PATH}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
