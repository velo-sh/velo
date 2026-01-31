#!/usr/bin/env python3
"""
HIO Visual Components - Unified Terminal Visual Enhancement Library
Supports CI auto-downgrade, accessibility mode, quiet mode, and JSON export.

Version: 2.0 (Unified Standard)
"""
import os
import sys
import json
import subprocess
import platform
from pathlib import Path
from typing import Optional, Tuple, List

# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================
IS_TTY = sys.stdout.isatty()
FORCE_VISUAL = os.getenv("HIO_FORCE_VISUAL", "").lower() in ("true", "1", "yes")
IS_CI = os.getenv("CI", "").lower() in ("true", "1", "yes") or os.getenv("GITHUB_ACTIONS") == "true"
IS_QUIET = os.getenv("HIO_QUIET", "").lower() in ("true", "1", "yes")
NO_COLOR = os.getenv("NO_COLOR", "") != "" or "--no-color" in sys.argv

# Rich library support (requires rich>=13.0.0, pinned in pyproject.toml)
RICH_AVAILABLE = False
console = None
Panel = None
Table = None

if not NO_COLOR and not IS_CI:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.progress import (
            Progress, 
            SpinnerColumn, 
            TextColumn, 
            BarColumn, 
            TaskProgressColumn,
            TimeElapsedColumn
        )
        console = Console(force_terminal=IS_TTY or FORCE_VISUAL)
        RICH_AVAILABLE = True
    except ImportError:
        pass

# ============================================================================
# SYSTEM INFO DETECTION
# ============================================================================

def get_cpu_info() -> Tuple[str, int]:
    """
    Return (CPU model, core count).
    Uses sysctl on macOS for accurate Apple Silicon detection.
    """
    core_count = os.cpu_count() or 0
    cpu_model = "Unknown"
    
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                cpu_model = result.stdout.strip()
            else:
                # Fallback for Apple Silicon
                result = subprocess.run(
                    ["sysctl", "-n", "hw.model"],
                    capture_output=True, text=True, timeout=2
                )
                cpu_model = result.stdout.strip() or platform.processor() or "Apple Silicon"
        except Exception:
            cpu_model = platform.processor() or "Apple Silicon"
    else:
        cpu_model = platform.processor() or "Unknown"
    
    return cpu_model, core_count


def get_velo_version() -> str:
    """Get Velo version by calling 'velo --version'."""
    try:
        # Try to find velo binary
        base_dir = Path(__file__).resolve().parent.parent.parent
        velo_bin = base_dir / "target" / "release" / "velo"
        if not velo_bin.exists():
            velo_bin = "velo"  # Fallback to PATH
        
        result = subprocess.run(
            [str(velo_bin), "--version"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return result.stdout.strip().split()[-1] if result.stdout else "dev"
    except Exception:
        pass
    return "dev"


# ============================================================================
# VISUAL COMPONENTS
# ============================================================================

def print_lab_environment():
    """Print LAB ENVIRONMENT panel with system info."""
    if IS_QUIET:
        return
    
    cpu_model, core_count = get_cpu_info()
    velo_version = get_velo_version()
    py_version = platform.python_version()
    os_info = f"{platform.system()} {platform.machine()}"
    
    if RICH_AVAILABLE:
        info_lines = [
            "[bold cyan]VELO PERFORMANCE LABS[/]",
            "[dim]High-Performance Python Runtime for the AI Era[/]",
            "",
            f"[dim]OS:[/] {os_info}  [dim]Python:[/] {py_version}",
            f"[dim]CPU:[/] {cpu_model} ({core_count} cores)",
            f"[dim]Velo:[/] v{velo_version}",
        ]
        console.print(Panel(
            "\n".join(info_lines),
            title="[bold white]LAB ENVIRONMENT[/]",
            border_style="cyan"
        ))
    else:
        print("=" * 60)
        print(" VELO PERFORMANCE LABS")
        print(f" OS: {os_info} | Python: {py_version}")
        print(f" CPU: {cpu_model} ({core_count} cores)")
        print(f" Velo: v{velo_version}")
        print("=" * 60)


def print_header(project: str, slogan: str):
    """Print Project Header (legacy compatibility)."""
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


def create_progress_context():
    """
    Create a Progress context manager.
    Returns (Progress, is_rich) tuple.
    """
    if RICH_AVAILABLE and not IS_QUIET:
        # High-performance progress bar configuration (low overhead)
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(
                bar_width=50, 
                style="grey23", 
                complete_style="bold bright_cyan", 
                finished_style="bold bright_green",
                pulse_style="bold cyan"
            ),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False, 
            refresh_per_second=20 # Higher refresh for smoother YouTube motion
        )
        return progress, True

    class SimpleProgress:
        def __init__(self):
            self._tasks = {}
            self._task_id = 0
        
        def __enter__(self): 
            return self
        
        def __exit__(self, *args): 
            # Print completion for any remaining tasks
            for task_id, task in self._tasks.items():
                if task["current"] >= task["total"]:
                    if not IS_QUIET:
                        print(f"  ✓ {task['desc']} [Done]", flush=True)
        
        def add_task(self, desc, total=100, **kwargs):
            task_id = self._task_id
            self._task_id += 1
            self._tasks[task_id] = {"desc": desc, "total": total, "current": 0}
            if not IS_QUIET:
                # Print task start with progress indicator
                print(f"  → {desc} [0/{total}]", end="", flush=True)
            return task_id
        
        def advance(self, task_id, advance=1):
            if task_id in self._tasks:
                self._tasks[task_id]["current"] += advance
                task = self._tasks[task_id]
                if not IS_QUIET:
                    # Update progress in place using carriage return
                    print(f"\r  → {task['desc']} [{task['current']}/{task['total']}]", end="", flush=True)
                    # Print newline when complete
                    if task["current"] >= task["total"]:
                        print(" ✓", flush=True)
        
        def remove_task(self, task_id):
            if task_id in self._tasks:
                task = self._tasks[task_id]
                if not IS_QUIET and task["current"] < task["total"]:
                    print(" ✓", flush=True)  # Finish line if removed early
                del self._tasks[task_id]
    
    return SimpleProgress(), False



def print_race_result(cpython_time: float, velo_time: float, mode: str = "Warm Cache", memory_data: Optional[Tuple] = None):
    """Print A/B comparison results with visual bar charts."""
    
    def format_time(t: float) -> str:
        """Format time, showing '<1ms' for sub-millisecond values."""
        if t < 0.001:
            return "<1ms"
        elif t < 1.0:
            return f"{t*1000:.1f}ms"
        else:
            return f"{t:.3f}s"
    
    if IS_QUIET:
        mem_str = ""
        if memory_data:
            mem_str = f" | Mem: {memory_data[0]:.1f}MB vs {memory_data[1]:.1f}MB"
        print(f"CPython: {format_time(cpython_time)} | Velo: {format_time(velo_time)} | Speedup: {cpython_time/max(velo_time, 0.0001):.1f}x{mem_str}")
        return
    
    max_time = max(cpython_time, velo_time)
    if max_time == 0:
        speedup = 1.0
        c_width = 0
        v_width = 0
    else:
        speedup = cpython_time / max(velo_time, 0.0001)
        # Calculate time progress bar widths
        c_width = int((cpython_time / max_time) * 30)
        v_width = int((velo_time / max_time) * 30)
    
    # Calculate memory progress bar widths (if provided)
    c_mem, v_mem = (0, 0)
    c_mem_width, v_mem_width = (0, 0)
    if memory_data:
        c_mem, v_mem = memory_data
        max_mem = max(c_mem, v_mem, 1)
        c_mem_width = int((c_mem / max_mem) * 30)
        v_mem_width = int((v_mem / max_mem) * 30)
    
    if RICH_AVAILABLE:
        table = Table(title=f"🏁 BENCHMARK RACE [dim](Mode: {mode})[/]", 
                      show_header=True, border_style="cyan")
        table.add_column("Metric", width=14)
        table.add_column("Runner", width=8)
        table.add_column("Progress", width=35)
        table.add_column("Value", width=18)
        
        c_bar = "█" * c_width + "░" * (30 - c_width)
        v_bar = "█" * v_width + "░" * (30 - v_width)
        
        # Time Rows
        table.add_row("Startup Time", "CPython", f"[bold red]{c_bar}[/]", f"[bold red]{format_time(cpython_time)}[/]")
        table.add_row("", "Velo", f"[bold bright_cyan]{v_bar}[/]", f"[bold bright_cyan]{format_time(velo_time)} ⚡[/]")
        
        # Memory Rows
        if memory_data:
            table.add_section()
            c_mbar = "█" * c_mem_width + "░" * (30 - c_mem_width)
            v_mbar = "█" * v_mem_width + "░" * (30 - v_mem_width)
            
            table.add_row("RSS Memory", "CPython", f"[red]{c_mbar}[/]", f"{c_mem:.1f}MB")
            table.add_row("", "Velo", f"[green]{v_mbar}[/]", f"{v_mem:.1f}MB (CoW) 📉")
        
        console.print(table)
    else:
        # Fallback Mode (Plain Text)
        c_bar = "#" * c_width + "." * (30 - c_width)
        v_bar = "#" * v_width + "." * (30 - v_width)
        
        print("-" * 60)
        print(f" HIO BENCHMARK RUN (Mode: {mode})")
        print("-" * 60)
        print(f" [Time] CPython:  [{c_bar}]  {format_time(cpython_time)}")
        print(f" [Time] Velo:     [{v_bar}]  {format_time(velo_time)} [FAST]")
        
        if memory_data:
            c_mbar = "#" * c_mem_width + "." * (30 - c_mem_width)
            v_mbar = "#" * v_mem_width + "." * (30 - v_mem_width)
            print("-" * 60)
            print(f" [RSS ] CPython:  [{c_mbar}]  {c_mem:.1f}MB")
            print(f" [RSS ] Velo:     [{v_mbar}]  {v_mem:.1f}MB (CoW)")
        
        print("-" * 60)


def print_verdict(speedup: float, mem_reduction: float = 0):
    """Print green Summary/Verdict panel."""
    if IS_QUIET:
        print(f"SUMMARY: Velo is {speedup:.2f}x faster")
        if mem_reduction > 0:
            print(f"Memory saved: {mem_reduction*100:.0f}%")
        return
    
    summary_text = f"[bold green]SUMMARY:[/] Velo is [bold yellow]{speedup:.2f}x[/] faster than traditional CPython cold starts."
    if mem_reduction > 0:
        summary_text += f"\n[dim]Memory saved: {mem_reduction*100:.0f}%[/]"
    
    if RICH_AVAILABLE:
        console.print(Panel(
            summary_text,
            title="[bold white]Verdict[/]",
            border_style="green"
        ))
    else:
        print("-" * 60)
        print(f" SUMMARY: Velo is {speedup:.2f}x faster")
        if mem_reduction > 0:
            print(f" Memory saved: {mem_reduction*100:.0f}%")
        print("-" * 60)


def print_score(score: float, mem_reduction: float = 0):
    """Print HIO Score (legacy compatibility)."""
    if IS_QUIET:
        print(f"HIO Score: {score} | Memory Saving: {mem_reduction*100:.0f}%")
        return
    
    if RICH_AVAILABLE:
        console.print(f"\n[bold yellow]>> HIO Score: {score}[/] [dim](Memory Saving: {mem_reduction*100:.0f}%)[/]")
    else:
        print(f"\n>> HIO Score: {score} [Memory Saving: {mem_reduction*100:.0f}%]")


def print_reproduce_hint(command: str):
    """Print reproduction hint."""
    if IS_QUIET:
        return
    
    if RICH_AVAILABLE:
        console.print(f"\n[dim]📎 Reproduce: {command}[/]")
    else:
        print(f"\n📎 Reproduce: {command}")


# ============================================================================
# DATA EXPORT
# ============================================================================

def export_results_json(
    path: str,
    cpython_times: List[float],
    velo_times: List[float],
    cpython_label: str = "CPython (Legacy Runtime)",
    velo_label: str = "Velo (Zygote Optimization)",
    sync_to_root: bool = True
):
    """
    Export benchmark results to JSON for Echarts visualization.
    
    Args:
        path: Output file path
        cpython_times: List of CPython timing samples (seconds)
        velo_times: List of Velo timing samples (seconds)
        cpython_label: Display label for CPython
        velo_label: Display label for Velo
        sync_to_root: If True, also write to project root result_100.json
    """
    import statistics
    
    cp_mean = statistics.mean(cpython_times) if cpython_times else 0
    ve_mean = statistics.mean(velo_times) if velo_times else 0.001
    speedup = cp_mean / max(ve_mean, 0.001)
    
    results = {
        "results": [
            {
                "name": cpython_label,
                "times": cpython_times,
                "mean": cp_mean
            },
            {
                "name": velo_label,
                "times": velo_times,
                "mean": ve_mean
            }
        ],
        "summary": f"Velo {speedup:.1f}x speedup"
    }
    
    # Write to specified path
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=4)
    
    if not IS_QUIET:
        if RICH_AVAILABLE:
            console.print(f"\n[green]✅ Data saved to {output_path}[/]")
        else:
            print(f"\n✅ Data saved to {output_path}")
    
    # Sync to project root for Echarts convenience
    if sync_to_root:
        try:
            base_dir = Path(__file__).resolve().parent.parent.parent
            root_result = base_dir / "result_100.json"
            with open(root_result, "w") as f:
                json.dump(results, f, indent=4)
            if not IS_QUIET:
                if RICH_AVAILABLE:
                    console.print(f"[green]✅ Synced to {root_result}[/]")
                else:
                    print(f"✅ Synced to {root_result}")
        except Exception:
            pass  # Ignore sync errors
    
    return results


def save_summary_metric(
    name: str, 
    result: str, 
    mem_save: Optional[float] = None, 
    speedup: Optional[float] = None,
    cpython_time: Optional[float] = None,
    velo_time: Optional[float] = None,
    cpython_rss: Optional[float] = None,
    velo_rss: Optional[float] = None
):
    """
    Append a metric to the global summary file for the demo.
    Format: '• {name}: {result} [MEM:{mem_save}%]'
    Also updates the JSON rich report if raw values are provided.
    """
    summary_file = os.getenv("HIO_SUMMARY_FILE", ".velo_summary.txt")
    
    # Use standard colon separator for parsed display
    # Add memory saving if provided
    mem_suffix = f"|{mem_save*100:.0f}" if mem_save is not None and mem_save > 0 else ""
    formatted_line = f"• {name}: {result}{mem_suffix}"
    
    try:
        with open(summary_file, "a") as f:
            f.write(f"{formatted_line}\n")
    except Exception:
        pass  # Fail silently to not disrupt benchmark

    # Automatically update rich report if raw data is provided
    if cpython_time is not None and velo_time is not None:
        save_rich_report(
            name, 
            cpython_time, 
            velo_time,
            cpython_rss or 0.0,
            velo_rss or 0.0
        )

def save_rich_report(
    name: str, 
    cpython_time: float, 
    velo_time: float,
    cpython_rss: float = 0.0,
    velo_rss: float = 0.0
):
    """
    Save or update a structured JSON report for all benchmarks.
    Stores raw CPython vs Velo comparison data for Web Dashboard.
    """
    report_file = os.getenv("HIO_REPORT_JSON", ".velo_report.json")
    
    data = {"timestamp": "", "benchmarks": []}
    if os.path.exists(report_file):
        try:
            with open(report_file, "r") as f:
                data = json.load(f)
        except Exception:
            pass
            
    # Update or add the benchmark
    found = False
    for b in data["benchmarks"]:
        if b["name"] == name:
            b["cpython_time"] = round(cpython_time * 1000, 2)  # ms
            b["velo_time"] = round(velo_time * 1000, 2)  # ms
            b["cpython_rss"] = round(cpython_rss, 1)  # MB
            b["velo_rss"] = round(velo_rss, 1)  # MB
            found = True
            break
            
    if not found:
        data["benchmarks"].append({
            "name": name,
            "cpython_time": round(cpython_time * 1000, 2),
            "velo_time": round(velo_time * 1000, 2),
            "cpython_rss": round(cpython_rss, 1),
            "velo_rss": round(velo_rss, 1)
        })
        
    try:
        with open(report_file, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def spinner_context(message: str):
    """Return Spinner context manager."""
    if RICH_AVAILABLE:
        return console.status(message, spinner="dots")
    else:
        class DummySpinner:
            def __enter__(self):
                print(f"{message}...")
                return self
            def __exit__(self, *args):
                pass
        return DummySpinner()


# ============================================================================
# DEMO / SELF-TEST
# ============================================================================

if __name__ == "__main__":
    # Demo all components
    print_lab_environment()
    print()
    print_header("HIO-005 (CLI Accelerator)", "Wait less, build more.")
    print()
    print_race_result(2.34, 0.12, "Cold Start", memory_data=(48.5, 5.2))
    print()
    print_verdict(19.5, 0.89)
    print()
    print_reproduce_hint("./run_hio.sh --compare --cold")
