import os

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {"status": "HIO-003 Active", "pid": os.getpid()}


@app.post("/dirty")
def dirty_state():
    # Generate side effects
    with open("/tmp/velo_test_dirty.txt", "w") as f:
        f.write("This should be purged by Velo Atomic Reset")
    return {"message": "State dirtied"}
