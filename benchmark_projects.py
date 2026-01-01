#!/usr/bin/env python3
"""
Create and run benchmarks in isolated uv projects.
Each benchmark has its own dependencies, separate from Velo.

Usage:
    python benchmark_projects.py --project fastapi
    python benchmark_projects.py --project django
    python benchmark_projects.py --project datascience
    python benchmark_projects.py --all
"""

import subprocess
import shutil
import time
import argparse
from pathlib import Path

VELO_BIN = Path(__file__).parent / "target/release/velo"
BENCHMARK_DIR = Path(__file__).parent.parent / "velo-benchmarks"


PROJECTS = {
    "fastapi": {
        "deps": ["fastapi", "uvicorn", "httpx", "pydantic", "sqlalchemy", "requests", "aiohttp", "numpy", "pandas"],
        "script": '''"""FastAPI microservice simulation - 60+ imports"""
# Web framework
from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator, root_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

# HTTP clients
import httpx
import requests
import aiohttp

# Database
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine

# Data processing
import numpy as np
import pandas as pd

# Standard library (all commonly used in real projects)
import os, sys, json, logging, datetime, uuid, re, hashlib
import asyncio, functools, itertools, collections, operator
import base64, secrets, hmac, struct, pickle, gzip, io, csv
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Callable, Awaitable
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

# Initialize
app = FastAPI(title="Benchmark API")
Base = declarative_base()
logging.basicConfig(level=logging.INFO)
print("FastAPI OK")
''',
    },
    "django": {
        "deps": ["django", "numpy", "pandas", "requests", "sqlalchemy", "httpx"],
        "script": '''"""Django web application simulation - 70+ imports"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
import django
from django.conf import settings
if not settings.configured:
    settings.configure(
        DEBUG=True, 
        SECRET_KEY='benchmark-secret-key-12345',
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True,
        INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth'],
    )
django.setup()

# Django ORM and HTTP
from django.http import HttpRequest, HttpResponse, JsonResponse, FileResponse
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.urls import path, include, reverse
from django.db import models, connection, transaction
from django.db.models import Q, F, Count, Sum, Avg
from django.core.cache import cache
from django.core.mail import send_mail
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.decorators import login_required
from django.forms import Form, ModelForm, CharField, IntegerField, EmailField
from django.template import Template, Context
from django.middleware.csrf import CsrfViewMiddleware

# External libs
import numpy as np
import pandas as pd
import requests
import httpx
from sqlalchemy import create_engine

# Standard library
import json, logging, datetime, uuid, re, hashlib, base64
import functools, itertools, collections, operator
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

print("Django OK")
''',
    },
    "datascience": {
        "deps": ["numpy", "pandas", "requests", "sqlalchemy", "httpx", "scipy", "scikit-learn"],
        "script": '''"""Data science pipeline simulation - 80+ imports"""
# Core data science
import numpy as np
from numpy import linalg, fft, random as np_random
from numpy.lib import stride_tricks
import pandas as pd
from pandas import DataFrame, Series, Timestamp, Timedelta
from pandas.api.types import is_numeric_dtype, is_string_dtype

# Scientific computing
import scipy
from scipy import stats, optimize, interpolate, signal
from scipy.spatial import distance
from scipy.sparse import csr_matrix, csc_matrix

# Machine learning
import sklearn
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.preprocessing import StandardScaler, MinMaxScaler, LabelEncoder
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.cluster import KMeans, DBSCAN
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline

# Database
from sqlalchemy import create_engine, text
import requests
import httpx

# Standard library
import os, sys, json, csv, io, re, math, random, statistics
import datetime, time, hashlib, uuid, logging
import functools, itertools, collections, operator
import pickle, gzip, base64, struct
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# Quick computation
df = pd.DataFrame({'a': np.random.randn(100), 'b': np.random.randn(100)})
X, y = df[['a']], (df['b'] > 0).astype(int)
model = LogisticRegression()
model.fit(X, y)

print("DataScience OK")
''',
    },
}


def setup_project(name: str, config: dict) -> Path:
    """Create isolated uv project with dependencies."""
    project_dir = BENCHMARK_DIR / f"bench_{name}"
    
    if project_dir.exists():
        print(f"  Project {name} already exists, reusing...")
    else:
        print(f"  Creating project {name}...")
        project_dir.mkdir(parents=True)
        
        # Write .python-version to pin Python 3.11 (must match Velo's linked Python)
        (project_dir / ".python-version").write_text("3.11\n")
        
        # Init uv project with neutral name
        subprocess.run(["uv", "init", "--no-workspace", "--name", f"bench_{name}"], cwd=project_dir, capture_output=True)
        
        # Add dependencies
        print(f"  Installing dependencies: {', '.join(config['deps'])}")
        result = subprocess.run(["uv", "add"] + config["deps"], cwd=project_dir, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Error installing dependencies: {result.stderr}")
    
    # Write test script
    script_path = project_dir / "bench.py"
    script_path.write_text(config["script"])
    
    return project_dir


def benchmark_project(name: str, project_dir: Path, iterations: int = 5):
    """Run benchmark comparing CPython vs Velo."""
    print(f"\n{'='*60}")
    print(f"Benchmarking: {name}")
    print(f"{'='*60}")
    
    script = project_dir / "bench.py"
    venv_python = project_dir / ".venv/bin/python"
    
    # Warmup
    subprocess.run([venv_python, script], cwd=project_dir, capture_output=True)
    subprocess.run([VELO_BIN, "run", script], cwd=project_dir, capture_output=True)
    
    # Clear Velo cache
    cache_dir = project_dir / ".velo_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    
    # Benchmark CPython
    cpython_times = []
    for i in range(iterations):
        start = time.perf_counter()
        subprocess.run([venv_python, script], cwd=project_dir, capture_output=True)
        cpython_times.append((time.perf_counter() - start) * 1000)
    
    # Benchmark Velo (cache miss first, then cache hit)
    velo_miss_times = []
    velo_hit_times = []
    
    for i in range(iterations):
        # Cache miss
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        start = time.perf_counter()
        subprocess.run([VELO_BIN, "run", script], cwd=project_dir, capture_output=True)
        velo_miss_times.append((time.perf_counter() - start) * 1000)
        
        # Cache hit
        start = time.perf_counter()
        subprocess.run([VELO_BIN, "run", script], cwd=project_dir, capture_output=True)
        velo_hit_times.append((time.perf_counter() - start) * 1000)
    
    # Results
    import statistics
    cpython_avg = statistics.mean(cpython_times)
    velo_miss_avg = statistics.mean(velo_miss_times)
    velo_hit_avg = statistics.mean(velo_hit_times)
    
    print(f"\nResults ({iterations} runs):")
    print(f"  CPython:          {cpython_avg:>8.1f}ms")
    print(f"  Velo (cache miss):{velo_miss_avg:>8.1f}ms ({(cpython_avg-velo_miss_avg)/cpython_avg*100:+.0f}%)")
    print(f"  Velo (cache hit): {velo_hit_avg:>8.1f}ms ({(cpython_avg-velo_hit_avg)/cpython_avg*100:+.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Velo against real projects")
    parser.add_argument("--project", "-p", choices=list(PROJECTS.keys()), help="Project to benchmark")
    parser.add_argument("--all", "-a", action="store_true", help="Benchmark all projects")
    parser.add_argument("--iterations", "-n", type=int, default=5, help="Iterations per benchmark")
    args = parser.parse_args()
    
    if not VELO_BIN.exists():
        print("Error: Build Velo first with 'cargo build --release'")
        return
    
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    
    projects_to_run = list(PROJECTS.keys()) if args.all else [args.project] if args.project else []
    
    if not projects_to_run:
        parser.print_help()
        return
    
    for name in projects_to_run:
        config = PROJECTS[name]
        project_dir = setup_project(name, config)
        benchmark_project(name, project_dir, args.iterations)


if __name__ == "__main__":
    main()
