#!/bin/bash
# Helper script for VHS demo to show summary with proper styling
# usage: ./show_summary.sh

SUMMARY_FILE=".velo_summary.txt"

if [ -f "$SUMMARY_FILE" ]; then
    # We use eval to properly parse the quoted strings inside the summary file
    # The summary file contains strings like '   • Metric: Value' which need to be passed as single args
    eval "gum style --border double --margin '1 2' --padding '2 4' --border-foreground 212 '📊 Results Summary:' '' $(cat "$SUMMARY_FILE")"
else
    # Fallback if no summary file
    gum style --border double --margin '1 2' --padding '2 4' --border-foreground 212 "📊 Results Summary:" "" "No data collected."
fi
