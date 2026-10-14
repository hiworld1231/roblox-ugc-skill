#!/usr/bin/env python3
"""Repository wrapper for the self-contained corpus maintenance tool."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / "plugins/roblox-ugc/skills/roblox-ugc/scripts/sync_corpus.py"), run_name="__main__")
