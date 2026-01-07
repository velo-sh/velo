import fastapi
import sys

# Official usage: Instantiate app
# We DO NOT run the server (uvicorn) to avoid blocking.
# This measures framework initialization cost.
app = fastapi.FastAPI()

print(f"FastAPI app created: {fastapi.__version__}")
