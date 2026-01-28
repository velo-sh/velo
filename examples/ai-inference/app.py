"""
Velo AI Serverless Demo - Embedding Service
"""

import time

from flask import Flask, jsonify, request
from model import embed

app = Flask(__name__)

# Record startup time for cold-start measurement
STARTUP_TIME = time.time()


@app.route("/")
def index():
    return jsonify({"service": "Velo AI Serverless Demo", "endpoints": ["/embed", "/health"]})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "uptime_s": time.time() - STARTUP_TIME})


@app.route("/embed", methods=["POST"])
def embed_endpoint():
    data = request.get_json() or {}
    texts = data.get("texts", ["hello world"])
    start = time.time()
    result = embed(texts)
    latency_ms = (time.time() - start) * 1000
    return jsonify({"embeddings": result, "latency_ms": f"{latency_ms:.2f}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
