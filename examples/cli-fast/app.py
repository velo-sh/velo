#!/usr/bin/env python3
"""
HIO-005: Heavy CLI Application Logic

This file represents a real-world, dependency-heavy CLI tool.
It contains NO benchmarking or Velo-specific measurement logic.
"""

import sys
# Heavy Imports
import rich.console
import click
import pydantic
from pydantic import BaseModel, Field
from typing import List, Optional

class SubItem(BaseModel):
    id: int
    name: str
    tags: List[str] = Field(default_factory=list)

class MainConfig(BaseModel):
    version: str
    debug: bool
    items: List[SubItem]
    metadata: Optional[dict] = None

def run_heavy_logic():
    """
    Simultate real-world business logic: Constructing complex Pydantic models.
    """
    data = []
    for i in range(100):
        data.append(MainConfig(
            version="1.0.0",
            debug=True,
            items=[SubItem(id=j, name=f"item_{j}", tags=["a", "b", "c"]) for j in range(10)]
        ))
    return len(data)

@click.command()
@click.option("--count", default=1, help="Number of times to run logic")
def main(count):
    console = rich.console.Console()
    console.print("[bold green]Heavy CLI Tool Starting...[/bold green]")
    
    for _ in range(count):
        result = run_heavy_logic()
    
    console.print(f"[bold blue]Success:[/bold blue] Processed {result} complex models.")

if __name__ == "__main__":
    main()
