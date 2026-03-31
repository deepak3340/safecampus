#!/bin/bash
echo "SafeGuard AI - Starting..."
# Paste your API key here:
export ANTHROPIC_API_KEY=YOUR_API_KEY_HERE
pip install flask -q
python app.py
