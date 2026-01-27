#!/usr/bin/env python3
"""
HIO-005: Heavy CLI Application Logic

This file represents a real-world, dependency-heavy CLI tool.
It contains NO benchmarking or Velo-specific measurement logic.
"""

# Heavy Imports
import click
import rich.console
from pydantic import BaseModel, Field


class SubItem(BaseModel):
    id: int
    name: str
    tags: list[str] = Field(default_factory=list)


class MainConfig(BaseModel):
    version: str
    debug: bool
    items: list[SubItem]
    metadata: dict | None = None


def run_heavy_logic():
    """
    Simulate real-world business logic: Constructing complex Pydantic models.
    """
    data = []
    for _ in range(100):
        data.append(
            MainConfig(
                version="1.0.0",
                debug=True,
                items=[SubItem(id=j, name=f"item_{j}", tags=["a", "b", "c"]) for j in range(10)],
            )
        )
    return len(data)


@click.command()
@click.option("--count", default=1, help="Number of times to run logic")
def main(count):
    if count < 1:
        raise click.BadParameter("count must be >= 1")

    console = rich.console.Console()
    console.print("[bold green]Heavy CLI Tool Starting...[/bold green]")

    result = 0
    for _ in range(count):
        result = run_heavy_logic()

    console.print(f"[bold blue]Success:[/bold blue] Processed {result} complex models.")


if __name__ == "__main__":
    main()
