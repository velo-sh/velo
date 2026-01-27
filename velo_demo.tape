# Velo HIO Demo - Complete 5-Project Benchmark Suite
# Run with: vhs velo_demo.tape
#
# This demo showcases all 5 HIO benchmark projects with 10 runs each

# Output configuration
Output velo_demo.gif
Output velo_demo.webm

# Terminal settings
Set FontSize 14
Set FontFamily "JetBrains Mono,Menlo,Monaco,monospace"
Set Theme "Dracula"
Set Width 1400
Set Height 800
Set Padding 20
Set TypingSpeed 30ms
Set Shell "zsh"
Set WindowBar Colorful
Set CursorBlink false

# Start demo
Hide
Type "cd /Users/avalon/Desktop/zaza/velo"
Enter
Type "clear"
Enter
Type "rm -f .velo_summary.txt"
Enter
Show

Sleep 2s

# Title
Hide
Type "gum style --border double --margin '1 2' --padding '2 4' --border-foreground 212 --align center '🚀 Velo Performance Labs - HIO Benchmark Suite' 'Running all 5 projects with 10 iterations each'"
Enter
Show
Sleep 1s

# ============================================
# HIO-005: CLI Accelerator
# ============================================
Type ""
Enter
Hide
Type "gum style --border normal --margin '1 0' --padding '0 2' --border-foreground 212 '📦 HIO-005: CLI Accelerator (TTFL Optimization)'"
Enter
Show
Sleep 500ms

Type "./examples/cli-fast/run_hio.sh --compare --runs=10"
Enter
Sleep 5s

# Pause for effect
Sleep 2s
Type "clear"
Enter
Sleep 500ms

# ============================================
# HIO-002: LangChain/Pydantic
# ============================================
Hide
Type "gum style --border normal --margin '1 0' --padding '0 2' --border-foreground 212 '📦 HIO-002: LangChain/Pydantic Fast-path (Schema Pre-lock)'"
Enter
Show
Sleep 500ms

Type "./examples/langchain-fast/run_hio.sh --compare --runs=10"
Enter
Sleep 15s

# Pause for effect
Sleep 2s
Type "clear"
Enter
Sleep 500ms

# ============================================
# HIO-003: FastAPI Instant
# ============================================
Hide
Type "gum style --border normal --margin '1 0' --padding '0 2' --border-foreground 212 '📦 HIO-003: FastAPI Instant Reset (Zygote Fork)'"
Enter
Show
Sleep 500ms

Type "./examples/fastapi-instant/run_hio.sh --compare --runs=10"
Enter
Sleep 8s

# Pause for effect
Sleep 2s
Type "clear"
Enter
Sleep 500ms

# ============================================
# HIO-004: Serverless Instant
# ============================================
Hide
Type "gum style --border normal --margin '1 0' --padding '0 2' --border-foreground 212 '📦 HIO-004: Serverless Instant (Cold Start Elimination)'"
Enter
Show
Sleep 500ms

Type "./examples/serverless-instant/run_hio.sh --compare --runs=10"
Enter
Sleep 5s

# Pause for effect
Sleep 2s
Type "clear"
Enter
Sleep 500ms

# ============================================
# HIO-001: Django Heavyweight
# ============================================
Hide
Type "gum style --border normal --margin '1 0' --padding '0 2' --border-foreground 212 '📦 HIO-001: Django Heavyweight (App Registry Warmup)'"
Enter
Show
Sleep 500ms

Type "./examples/django-heavy/run_hio.sh --compare --runs=10"
Enter
Sleep 5s

# ============================================
# Final Summary
# ============================================
Sleep 2s
Type "clear"
Enter
Sleep 500ms

Type ""
Enter
Hide
Type "./examples/scripts/show_summary.sh"
Enter
Show
Type ""
Enter


Sleep 5s
