#!/usr/bin/env python3
"""
Benchmark Scaffolder
Generates directory structure and templates for Velo Top 100 Benchmarks.
"""
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
TARGETS = [
    # Data/ML
    ("ml", "pandas"),
    ("ml", "scikit-learn"),
    ("ml", "matplotlib"),
    ("ml", "scipy"),
    
    # Web
    ("web", "django"),
    ("web", "flask"),
    
    # Library
    ("library", "sqlalchemy"),
    ("library", "pydantic"),
    ("library", "boto3"),
    ("library", "pyyaml"),
    ("library", "pillow"),
    
    # CLI
    ("cli", "pytest"),
    ("cli", "click"),
    ("cli", "typer"),
    ("cli", "rich"),

    # Batch 3
    ("library", "six"),
    ("library", "python-dateutil"),
    ("library", "certifi"),
    ("library", "idna"),
    ("library", "pyasn1"),
    ("library", "docutils"),
    ("library", "chardet"),
    ("library", "jmespath"),
    ("library", "botocore"),
    ("library", "colorama"),
    ("library", "s3transfer"),
    ("library", "packaging"),
    ("library", "attrs"),
    ("library", "psutil"),
    ("library", "protobuf"),
    ("library", "jinja2"),
    ("library", "rsa"),
    ("library", "setuptools"),
    ("library", "wheel"),
    ("cli", "pip"),

    # Batch 4
    ("library", "charset-normalizer"),
    ("library", "typing-extensions"),
    ("library", "aiobotocore"),
    ("ml", "tensorflow"),
    ("ml", "torch"),
    ("library", "beautifulsoup4"),
    ("web", "aiohttp"),
    ("library", "cryptography"),
    ("library", "cffi"),
    ("library", "pycparser"),
    ("cli", "virtualenv"),
    ("library", "tqdm"),
    ("library", "lxml"),
    ("library", "wrapt"),
    ("library", "greenlet"),
    ("cli", "coverage"),
    ("cli", "pylint"),
    ("library", "google-auth"),
    ("library", "googleapis-common-protos"),
    ("library", "soupsieve"),

    # Batch 5
    ("ml", "opencv-python"),
    ("ml", "pyarrow"),
    ("library", "grpcio"),
    ("library", "simplejson"),
    ("web", "uvicorn"),
    ("web", "starlette"),
    ("library", "httpx"),
    ("library", "pymongo"),
    ("library", "redis"),
    ("library", "psycopg2-binary"),
    ("web", "gunicorn"),
    ("cli", "alembic"),
    ("cli", "isort"),
    ("cli", "flake8"),
    ("cli", "mypy"),
    ("library", "python-dotenv"),
    ("library", "pytz"),
    ("library", "dnspython"),
    ("library", "cachetools"),
    ("library", "markupsafe"),

    # Batch 6
    ("library", "zipp"),
    ("library", "importlib-metadata"),
    ("library", "platformdirs"),
    ("library", "more-itertools"),
    ("library", "tomli"),
    ("library", "jsonschema"),
    ("library", "pluggy"),
    ("library", "filelock"),
    ("library", "pyparsing"),
    ("library", "joblib"),
    ("library", "threadpoolctl"),
    ("library", "fonttools"),
    ("library", "regex"),
    ("library", "msgpack"),
    ("library", "anyio"),
    ("library", "distlib"),
    ("library", "pyopenssl"),
    ("library", "twisted"),
    ("library", "celery"),
    ("library", "kombu"),
]

TEMPLATES = {
    "hello.py": {
        "common": 'import {pkg}\nprint(f"{pkg} version: {{ {pkg}.__version__ }}")',
        "web": 'import {pkg}\n# Framework init only\napp = {pkg}.APP_CLASS()\nprint(f"{pkg} app created")',
        "cli": 'import sys\nimport {pkg}\n# CLI tool verification\nprint(f"{pkg} imported")',
    },
    "benchmark.toml": '''
[meta]
category = "{category}"
package = "{pkg}"

[test]
entry_point = "hello.py"
expected_output = ".*"
preload_modules = ["{pkg}"]
timeout = 30
'''
}

def scaffold():
    for category, pkg in TARGETS:
        pkg_slug = pkg.replace("-", "_") # Python import safety
        target_dir = ROOT_DIR / category / pkg
        
        if target_dir.exists():
            print(f"Skipping existing: {category}/{pkg}")
            continue
            
        print(f"Scaffolding: {category}/{pkg}")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. hello.py
        hello_path = target_dir / "hello.py"
        if category == "web":
            # Rough guess, user must fix
            content = TEMPLATES["hello.py"]["web"].replace("{pkg}", pkg_slug)
        elif category == "cli":
             content = TEMPLATES["hello.py"]["cli"].replace("{pkg}", pkg_slug)
        else:
            content = TEMPLATES["hello.py"]["common"].replace("{pkg}", pkg_slug)
            
        with open(hello_path, "w") as f:
            f.write(content)
            
        # 2. benchmark.toml
        toml_path = target_dir / "benchmark.toml"
        toml_content = TEMPLATES["benchmark.toml"].replace("{category}", category)\
                                                  .replace("{pkg}", pkg)
        with open(toml_path, "w") as f:
            f.write(toml_content)

if __name__ == "__main__":
    scaffold()
