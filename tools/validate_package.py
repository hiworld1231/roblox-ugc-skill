#!/usr/bin/env python3
"""Validate package identity, containment, authored links and source integrity."""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/roblox-ugc"
SKILL = PLUGIN / "skills/roblox-ugc"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true", help="Also use jsonschema against the official portable manifest schema")
    args = parser.parse_args()
    problems = []
    manifests = [json.loads((PLUGIN / path).read_text()) for path in ("plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json")]
    for key in ("name", "version"):
        if len({m[key] for m in manifests}) != 1:
            problems.append("Manifest identity mismatch: " + key)
    if len(manifests[0]["extensions"]["com.openai"]["interface"]["shortDescription"]) > 30:
        problems.append("Portable shortDescription exceeds 30 characters")
    for marketplace in (".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"):
        data = json.loads((ROOT / marketplace).read_text())
        if data["name"] != "roblox-ugc-skill" or data["plugins"][0]["name"] != manifests[0]["name"]:
            problems.append("Marketplace identity mismatch: " + marketplace)
        source = data["plugins"][0]["source"]
        path = source["path"] if isinstance(source, dict) else source
        if (ROOT / path).resolve() != PLUGIN.resolve():
            problems.append("Marketplace source resolves outside expected plugin")
    for path in PLUGIN.rglob("*"):
        if path.is_symlink():
            problems.append("Symlink in package: " + str(path))
    for path in [SKILL / "SKILL.md", SKILL / "ATTRIBUTION.md", *SKILL.glob("references/*.md")]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            if target.startswith(("https://", "http://", "#")):
                continue
            target = target.split("#")[0]
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(SKILL.resolve()) or not resolved.exists():
                problems.append(f"Invalid authored local link {path.name}: {target}")
    for path in ("licenses/ROBLOX-LICENSE", "licenses/ROBLOX-LICENSE-CODE", "licenses/PROJECT-LICENSE", "assets/templates.json"):
        if not (SKILL / path).is_file():
            problems.append("Missing standalone license/resource: " + path)
    spec = importlib.util.spec_from_file_location("corpus", SKILL / "scripts/corpus.py")
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    integrity = corpus.audit()
    problems.extend(integrity["problems"])
    if args.schema:
        import jsonschema
        url = manifests[0]["$schema"]
        with urllib.request.urlopen(url, timeout=30) as response:
            schema = json.loads(response.read())
        jsonschema.Draft202012Validator(schema).validate(manifests[0])
    result = {"ok": not problems, "problems": problems, "version": manifests[0]["version"],
              "corpus": integrity, "schema_validated": args.schema}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
