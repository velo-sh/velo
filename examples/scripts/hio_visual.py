#!/usr/bin/env python3
"""
HIO Visual Components - Terminal Visual Enhancement Library
Supports CI auto-downgrade, accessibility mode, and quiet mode
"""
import os
import sys

# Environment Detection
IS_TTY = sys.stdout.isatty()
# Allow forcing visual effects via env var (for non-TTY demo envs)
FORCE_VISUAL = os.getenv("HIO_FORCE_VISUAL", "").lower() in ("true", "1", "yes")

IS_CI = os.getenv("CI", "").lower() in ("true", "1", "yes")
IS_QUIET = os.getenv("HIO_QUIET", "").lower() in ("true", "1", "yes")
NO_COLOR = os.getenv("NO_COLOR", "") != "" or "--no-color" in sys.argv

# Try importing rich, degrade on failure
RICH_AVAILABLE = False
# If not quiet, and (is TTY or forced), and not CI (unless forced)
if not IS_QUIET and (IS_TTY or FORCE_VISUAL) and (not IS_CI or FORCE_VISUAL):
    try:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        from rich.table import Table
        from rich.panel import Panel
        RICH_AVAILABLE = True
    except ImportError:
        pass

# Create Console instance
if RICH_AVAILABLE:
    console = Console(force_terminal=True, force_interactive=True, no_color=NO_COLOR)
else:
    console = None


def print_header(project: str, slogan: str):
    """Print Project Header"""
    if IS_QUIET:
        return
    
    if RICH_AVAILABLE:
        console.print(Panel(
            f"[bold cyan]{project}[/]\n[dim]{slogan}[/]",
            title="🚀 Velo HIO",
            border_style="cyan"
        ))
    else:
        print("=" * 50)
        print(f" HIO PROJECT: {project}")
        print(f" SLOGAN: {slogan}")
        print("=" * 50)


def print_race_result(cpython_time: float, velo_time: float, mode: str = "Warm Cache", memory_data: Optional[Tuple] = None):
    """Print A/B comparison results (supports time and memory dimensions)"""
    if IS_QUIET:
        mem_str = ""
        if memory_data:
            mem_str = f" | Mem: {memory_data[0]:.1f}MB vs {memory_data[1]:.1f}MB"
        print(f"CPython: {cpython_time:.3f}s | Velo: {velo_time:.3f}s | Speedup: {cpython_time/velo_time:.1f}x{mem_str}")
        return
    
    speedup = cpython_time / max(velo_time, 0.001)
    max_time = max(cpython_time, velo_time)
    
    # Calculate time progress bar
    c_width = int((cpython_time / max_time) * 30)
    v_width = int((velo_time / max_time) * 30)
    
    # Calculate memory progress bar (if provided)
    c_mem, v_mem = (0, 0)
    if memory_data:
        c_mem, v_mem = memory_data
        max_mem = max(c_mem, v_mem, 1) # Avoid division by zero
        c_mem_width = int((c_mem / max_mem) * 30)
        v_mem_width = int((v_mem / max_mem) * 30)
    
    if RICH_AVAILABLE:
        table = Table(title=f"🏁 STARTUP RACE [dim](Measured under: {mode})[/]", 
                      show_header=True, border_style="cyan")
        table.add_column("Metric", width=12)
        table.add_column("Runner", width=8)
        table.add_column("Progress", width=35)
        table.add_column("Value", width=15)
        
        c_bar = "█" * c_width + "░" * (30 - c_width)
        v_bar = "█" * v_width + "░" * (30 - v_width)
        
        # Time Rows
        table.add_row("Startup Time", "CPython", f"[red]{c_bar}[/]", f"{cpython_time:.3f}s")
        table.add_row("", "Velo", f"[green]{v_bar}[/]", f"{velo_time:.3f}s ⚡")
        
        # Memory Rows
        if memory_data:
            table.add_section()
            c_mbar = "█" * c_mem_width + "░" * (30 - c_mem_width)
            v_mbar = "█" * v_mem_width + "░" * (30 - v_mem_width)
            
            table.add_row("RSS Memory", "CPython", f"[red]{c_mbar}[/]", f"{c_mem:.1f}MB")
            table.add_row("", "Velo", f"[green]{v_mbar}[/]", f"{v_mem:.1f}MB (CoW) 📉")
        
        console.print(table)
        console.print(f"\n[bold green]>>> Velo wins by {speedup:.1f}x![/]")
        if memory_data:
             console.print(f"[dim]    (And saves {(c_mem-v_mem)/c_mem*100:.0f}% memory)[/]")

    else:
        # Fallback Mode (Plain Text - Robust ASCII)
        try:
            c_bar = "#" * c_width + "." * (30 - c_width)
            v_bar = "#" * v_width + "." * (30 - v_width)
            
            print("-" * 60)
            print(f" HIO BENCHMARK RUN (Measured under: {mode})")
            print("-" * 60)
            print(f" [Time] CPython:  [{c_bar}]  {cpython_time:.2f}s")
            print(f" [Time] Velo:     [{v_bar}]  {velo_time:.2f}s [FAST]")
            
            if memory_data:
                c_mem, v_mem = memory_data
                c_mbar = "#" * c_mem_width + "." * (30 - c_mem_width)
                v_mbar = "#" * v_mem_width + "." * (30 - v_mem_width)
                print("-" * 60)
                print(f" [RSS ] CPython:  [{c_mbar}]  {c_mem:.1f}MB")
                print(f" [RSS ] Velo:     [{v_mbar}]  {v_mem:.1f}MB (CoW)")
                
            print("-" * 60)
            print(f" >>> Velo wins by {speedup:.1f}x!")
            print("-" * 60)
        except Exception as e:
            print(f"[ERROR] Failed to render ASCII table: {e}")
            # Fallback
            print(f"CPython: {cpython_time}s | Velo: {velo_time}s")


def print_score(score: float, mem_reduction: float):
    """Print HIO Score"""
    if IS_QUIET:
        print(f"HIO Score: {score} | Memory Saving: {mem_reduction*100:.0f}%")
        return
    
    if RICH_AVAILABLE:
        console.print(f"\n[bold yellow]>> HIO Score: {score}[/] [dim](Calculated with {mem_reduction*100:.0f}% Memory Saving)[/]")
    else:
        print(f"\n>> HIO Score: {score} [Calculated with {mem_reduction*100:.0f}% Memory Saving]")


def print_reproduce_hint(command: str):
    """Print reproduction hint"""
    if IS_QUIET:
        return
    
    if RICH_AVAILABLE:
        console.print(f"\n[dim]📎 Reproduce: {command} | Full docs: velo.dev/hio[/]")
    else:
        print(f"\n📎 Reproduce: {command} | Full docs: velo.dev/hio")


def spinner_context(message: str):
    """Return Spinner context manager"""
    if RICH_AVAILABLE:
        return console.status(message, spinner="dots")
    else:
        # Degrade to simple print
        class DummySpinner:
            def __enter__(self):
                print(f"{message}...")
                return self
            def __exit__(self, *args):
                pass
        return DummySpinner()


if __name__ == "__main__":
    # Demo
    print_header("HIO-001 (Django)", "Wait less, build more.")
    print_race_result(2.34, 0.12, "Cold Start")
    print_score(92.2, 0.80)
    print_reproduce_hint("./run_hio.sh --compare --cold")
