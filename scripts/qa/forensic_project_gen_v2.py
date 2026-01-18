#!/usr/bin/env python3
"""
Velo Forensic Project Generator v2 (Gold 1000 Edition)
Generates high-fidelity, industrial-grade test suites that demonstrate Zygote COW benefits.

Key Enhancements:
- Heavy imports (pydantic-like models, typing, dataclasses)
- Larger per-module memory footprint
- More realistic test structure
"""
import argparse
import shutil
from pathlib import Path


def generate_gold_specimen(output_dir: Path, total_tests: int, heavy: bool = True):
    """Generate a forensic gold standard test project."""
    print(f"🧬 Generating {'Heavy' if heavy else 'Light'} Gold Specimen: {output_dir} ({total_tests} tests)")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 1. Infrastructure Setup
    src_root = output_dir / "src" / "velo_app"
    test_root = output_dir / "tests"
    src_root.mkdir(parents=True)
    test_root.mkdir(parents=True)

    # Create __init__.py for velo_app
    (src_root / "__init__.py").write_text('"""Velo App - Forensic Benchmark Package"""')

    # 2. Create Heavy Model System (simulates pydantic/django imports)
    # This is what Zygote should cache in the parent process
    models_file = src_root / "models.py"
    models_file.write_text('''"""
Heavy Model System - Simulates Pydantic/Django ORM Load
This file is imported by ALL tests - Zygote should COW-share it.
"""
import dataclasses
import typing
import json
import hashlib
import base64
import datetime
import decimal
import enum
import functools
import itertools
import re
import uuid

# Simulate a large type registry (like Pydantic's model registry)
_TYPE_REGISTRY: dict = {}


class FieldType(enum.Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    UUID = "uuid"


@dataclasses.dataclass
class FieldDefinition:
    name: str
    field_type: FieldType
    required: bool = True
    default: typing.Any = None
    validators: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ModelDefinition:
    name: str
    fields: list
    table_name: str = ""

    def __post_init__(self):
        if not self.table_name:
            self.table_name = self.name.lower() + "s"
        _TYPE_REGISTRY[self.name] = self


# Pre-register 100 heavy models (simulates Django app startup)
HEAVY_MODELS = []
for i in range(100):
    model = ModelDefinition(
        name=f"HeavyModel{i}",
        fields=[
            FieldDefinition(f"field_{j}", FieldType.STRING)
            for j in range(20)
        ]
    )
    HEAVY_MODELS.append(model)


# Large constant data (simulates i18n strings, config, etc.)
TRANSLATIONS = {f"key_{i}": f"translated_value_{i}" * 10 for i in range(500)}
CONFIG_CACHE = {f"config_{i}": {"nested": {"data": list(range(100))}} for i in range(50)}


def get_model(name: str) -> typing.Optional[ModelDefinition]:
    return _TYPE_REGISTRY.get(name)


def validate_data(model_name: str, data: dict) -> bool:
    model = get_model(model_name)
    if not model:
        return False
    for field in model.fields:
        if field.required and field.name not in data:
            return False
    return True
''')

    # 3. Create Services (5 services x 4 modules x 4 submodules = 80 files)
    services = ["auth", "billing", "compute", "storage", "analytics"]

    for service in services:
        svc_path = src_root / service
        svc_path.mkdir(exist_ok=True)
        (svc_path / "__init__.py").write_text(f'"""Service: {service}"""')

        for m in range(4):  # 4 modules per service
            mod_path = svc_path / f"module_{m}"
            mod_path.mkdir(exist_ok=True)
            (mod_path / "__init__.py").write_text("")

            for s in range(4):  # 4 submodules
                sub_path = mod_path / f"sub_{s}"
                sub_path.mkdir(exist_ok=True)
                (sub_path / "__init__.py").write_text("")

                # Logic file that imports the heavy models
                logic_file = sub_path / "logic.py"
                logic_file.write_text(f'''"""
Service: {service}, Module: {m}, Sub: {s}
Each logic file imports the heavy models - Zygote should COW-share.
"""
import math
import hashlib
from velo_app.models import HEAVY_MODELS, get_model, validate_data, TRANSLATIONS

# Local computation state
_CACHE = {{}}

def process_data_{service}_{m}_{s}(x: int) -> float:
    """Process data with model validation overhead."""
    # Access shared models (should be COW)
    model = get_model(f"HeavyModel{{x % 100}}")
    
    # Some actual computation
    result = math.sqrt(abs(x)) if x >= 0 else 0.0
    
    # Cache lookup (simulates ORM cache)
    cache_key = f"{{x}}_{{model.name if model else 'none'}}"
    if cache_key not in _CACHE:
        _CACHE[cache_key] = result
    
    return result


def get_translation(key: str) -> str:
    """Access shared translation data."""
    return TRANSLATIONS.get(key, key)
''')

    # 4. Create Test Suite
    tests_per_service = total_tests // len(services)

    for idx in range(total_tests):
        service = services[idx % len(services)]
        m_idx = (idx // 4) % 4
        s_idx = (idx // 16) % 4

        # Nested test directory
        test_dir = test_root / f"layer_1_{service}" / f"layer_2_mod_{m_idx}" / f"layer_3_sub_{s_idx}"
        test_dir.mkdir(parents=True, exist_ok=True)

        # Only create __init__.py once per directory
        init_file = test_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")

        test_file = test_dir / f"test_forensic_{idx}.py"

        # Cross-service import for extra stress
        cross_service = services[(idx + 1) % len(services)]
        cross_m = (idx + 7) % 4
        cross_s = (idx + 3) % 4

        test_file.write_text(f'''"""Forensic Test Case #{idx}"""
import sys
import pytest

# Heavy import - Zygote should COW-share this
from velo_app.models import HEAVY_MODELS, get_model

# Service imports
from velo_app.{service}.module_{m_idx}.sub_{s_idx} import logic


class TestForensic{idx}:
    """Test class for case {idx}."""
    
    def test_primary_processing(self):
        """Test primary data processing path."""
        res = logic.process_data_{service}_{m_idx}_{s_idx}({idx})
        assert res >= 0
        
    def test_model_access(self):
        """Test heavy model registry access (COW target)."""
        model = get_model(f"HeavyModel{{{idx} % 100}}")
        assert model is not None
        assert len(HEAVY_MODELS) == 100
        
    def test_module_loaded(self):
        """Verify heavy modules are in memory (COW shared)."""
        assert "velo_app.models" in sys.modules
        assert "velo_app.{service}" in sys.modules
''')

    # 5. Root conftest with realistic session fixture
    (test_root / "conftest.py").write_text('''"""
Root conftest - Global fixtures loaded once by Zygote.
"""
import pytest
import time

# Import heavy modules at conftest level (Zygote caches this)
from velo_app.models import HEAVY_MODELS, _TYPE_REGISTRY, TRANSLATIONS


@pytest.fixture(scope="session", autouse=True)
def heavy_session_setup():
    """
    Simulate expensive session setup.
    In Zygote mode, this runs ONCE in the parent and is COW-shared.
    In subprocess mode, this runs in EVERY worker.
    """
    # Validate all models are loaded
    assert len(HEAVY_MODELS) == 100
    assert len(_TYPE_REGISTRY) >= 100
    assert len(TRANSLATIONS) == 500
    yield
    # Cleanup


@pytest.fixture(scope="module")
def module_context():
    """Per-module context."""
    return {"initialized": True}
''')

    # 6. Create pyproject.toml for the specimen
    (output_dir / "pyproject.toml").write_text(f'''[project]
name = "gold_specimen"
version = "1.0.0"
description = "Velo Forensic Benchmark Specimen ({total_tests} tests)"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
''')

    print(f"✅ Gold Specimen ready at {output_dir}")
    print(f"   - {total_tests} test files")
    print(f"   - {total_tests * 4} test cases (4 per file)")
    print(f"   - 100 heavy models (COW target)")
    print(f"   - 500 translation entries")
    print(f"   - 5 services x 4 modules x 4 submodules = 80 logic files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Gold Specimen for Velo Benchmarking")
    parser.add_argument("--count", type=int, required=True, help="Number of test files")
    parser.add_argument("--output", type=str, required=True, help="Output directory")
    parser.add_argument("--light", action="store_true", help="Generate light specimen (no heavy imports)")
    args = parser.parse_args()
    generate_gold_specimen(Path(args.output), args.count, heavy=not args.light)
