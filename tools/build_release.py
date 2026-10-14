#!/usr/bin/env python3
"""Build self-contained release archives; validates their contents by extraction."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/roblox-ugc"
SKILL = PLUGIN / "skills/roblox-ugc"


def pack(source, output, prefix):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                if path.is_symlink():
                    raise ValueError("Symlink cannot be packaged")
                archive.write(path, prefix + "/" + path.relative_to(source).as_posix())


def main():
    subprocess.run([sys.executable, str(ROOT / "tools/validate_package.py")], check=True)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    version = json.loads((PLUGIN / "plugin.json").read_text())["version"]
    plugin = dist / f"roblox-ugc-plugin-v{version}.zip"
    skill = dist / f"roblox-ugc-skill-v{version}.zip"
    pack(PLUGIN, plugin, "roblox-ugc")
    pack(SKILL, skill, "roblox-ugc")
    with tempfile.TemporaryDirectory(prefix="ugc-release-check-") as temp:
        with zipfile.ZipFile(skill) as archive:
            archive.extractall(temp)
        extracted = Path(temp) / "roblox-ugc"
        subprocess.run([sys.executable, str(extracted / "scripts/corpus.py"), "audit", "--json"], check=True, capture_output=True)
        subprocess.run([sys.executable, str(extracted / "scripts/asset.py"), "templates"], check=True, capture_output=True)
        for helper in ("blender_mcp.py", "rebake.py"):
            subprocess.run([sys.executable, str(extracted / "scripts" / helper), "--help"], check=True, capture_output=True)
        if not (extracted / "scripts/blender_mcp_requirements.lock").is_file():
            raise ValueError("Standalone Blender MCP dependency lock missing")
        if not (extracted / "SKILL.md").is_file():
            raise ValueError("Standalone skill entrypoint missing")
    shutil.copyfile(SKILL / "corpus/coverage.json", dist / "coverage.json")
    shutil.copyfile(ROOT / "docs/validation.json", dist / "validation.json")
    files = [plugin, skill, dist / "coverage.json", dist / "validation.json"]
    for name in ("video-analysis.md", "blender-mcp-validation.json", "rbx-toolbox-audit.json", "studio-control-validation.json", "remesh-rebake-validation.json"):
        source = ROOT / "docs" / name
        if source.is_file():
            shutil.copyfile(source, dist / name)
            files.append(dist / name)
    sums = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in files)
    (dist / "SHA256SUMS").write_text(sums)
    print(json.dumps({"files": [{"name": p.name, "bytes": p.stat().st_size} for p in files], "standalone_extract_smoke": "PASS"}, indent=2))


if __name__ == "__main__":
    main()
