#!/bin/bash
# HIO Executive Summary Dashboard (VHS Optimized)
# Replaces simple gum box with a multi-layered, premium performance dashboard.

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SUMMARY_FILE="${HIO_SUMMARY_FILE:-.velo_summary.txt}"
COLOR_TITLE="212"    # Hot Pink
COLOR_ACCENT="045"   # Electric Cyan (Velo)
COLOR_MUTE="240"     # Gray
COLOR_DATA="082"     # Neon Green

# --- PRE-FLIGHT ---
if [ ! -f "$SUMMARY_FILE" ]; then
    gum style --border rounded --padding "1 2" --border-foreground "$COLOR_TITLE" "📊 No Data Collected."
    exit 0
fi

# --- RENDER HEADER ---
echo ""
gum style --foreground "$COLOR_TITLE" --bold "  📊 PERFORMANCE BENCHMARK REPORT"
echo "  $(gum style --foreground "$COLOR_MUTE" "──────────────────────────────────────────")"
echo ""

# --- RENDER BODY ---
# We read the summary and style the key metrics dynamically
while IFS= read -r line; do
    # Skip empty lines
    [[ -z "$line" ]] && continue
    
    # Parse format: '• Key: Value|MemSave'
    key=$(echo "$line" | cut -d':' -f1 | sed 's/^• //')
    full_val=$(echo "$line" | cut -d':' -f2- | sed 's/^[[:space:]]*//')
    
    # Split value and memory saving
    val=$(echo "$full_val" | cut -d'|' -f1)
    mem=$(echo "$full_val" | cut -d'|' -s -f2)
    
    # Left column: Muted Key (with fixed padding for alignment)
    left=$(gum style --width 30 --foreground "$COLOR_MUTE" "  • $key")
    
    # Right column: Speed + Mem (if available)
    if [ -n "$mem" ]; then
        speed_part=$(gum style --bold --foreground "$COLOR_ACCENT" "$val")
        mem_part=$(gum style --foreground "$COLOR_DATA" "($mem% RSS Saved 📉)")
        right=$(gum join --horizontal --align bottom "$speed_part" " " "$mem_part")
    else
        right=$(gum style --bold --foreground "$COLOR_ACCENT" "$val")
    fi
    
    # Join them side-by-side
    gum join --horizontal "$left" "$right"
done < "$SUMMARY_FILE"

# --- RENDER FOOTER ---
echo ""
echo "  $(gum style --foreground "$COLOR_MUTE" "──────────────────────────────────────────")"
footer_label=$(gum style --foreground "$COLOR_MUTE" "  VELO PROTOCOL:")
footer_status=$(gum style --foreground "$COLOR_DATA" --bold " [OPTIMIZED / TITANIUM]")
gum join --horizontal "$footer_label" "$footer_status"
echo ""
