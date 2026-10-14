#!/usr/bin/env python3
"""Prepare, preflight and export Roblox avatar projects. Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import zlib
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
RULES = json.loads((SKILL / "assets/rules.json").read_text())
KINDS = tuple(k for k in RULES if k != "snapshot_date")


def finding(check, status, evidence, source):
    return {"check": check, "status": status, "evidence": evidence, "source": source, "rule_snapshot": RULES["snapshot_date"]}


def report(kind, checks, **extra):
    return {"asset_kind": kind, "stage": "offline-preflight", "checks": checks,
        "blocking_failures": sum(c["status"] == "FAIL" for c in checks),
        "requires_studio_validation": True, "marketplace_approved": False, **extra}


def image_info(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset, dimensions, ended, idat = 8, None, False, bytearray()
        while offset < len(data):
            if offset + 12 > len(data):
                raise ValueError("Truncated PNG chunk")
            size = int.from_bytes(data[offset:offset+4], "big")
            typ = data[offset+4:offset+8]
            chunk = data[offset+8:offset+8+size]
            end = offset + 12 + size
            if end > len(data):
                raise ValueError("Truncated PNG data")
            crc = int.from_bytes(data[end-4:end], "big")
            if zlib.crc32(typ + chunk) & 0xFFFFFFFF != crc:
                raise ValueError("PNG CRC mismatch")
            if typ == b"IHDR":
                if dimensions is not None or size != 13:
                    raise ValueError("Invalid PNG header")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk)
                if not width or not height or compression or filtering:
                    raise ValueError("Invalid PNG dimensions or compression")
                dimensions = [width, height]
            if typ == b"IDAT":
                idat.extend(chunk)
            if typ == b"IEND":
                ended = True
                break
            offset = end
        if not dimensions or not ended or not idat:
            raise ValueError("PNG lacks required chunks")
        # Bound decompression: inspect structure without allocating an unbounded image.
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(idat), 64 * 1024 * 1024)
        if not decoder.eof:
            raise ValueError("Invalid or excessive PNG compressed data")
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
        if channels is None:
            raise ValueError("Invalid PNG color type")
        if not interlace:
            stride = (dimensions[0] * channels * depth + 7) // 8
            if len(raw) != (stride + 1) * dimensions[1]:
                raise ValueError("PNG pixel length mismatch")
            if any(raw[i * (stride + 1)] > 4 for i in range(dimensions[1])):
                raise ValueError("Invalid PNG filter")
        return {"format": "PNG", "dimensions": dimensions, "container_checked": True, "pixels_decoded": False}
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                offset += 1
                continue
            marker = data[offset+1]
            offset += 2
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(data[offset:offset+2], "big")
            if length < 2 or offset + length > len(data):
                raise ValueError("Truncated JPEG segment")
            if marker in (0xC0, 0xC1, 0xC2):
                if length < 8:
                    raise ValueError("Invalid JPEG frame")
                height, width = struct.unpack(">HH", data[offset+3:offset+7])
                if not width or not height or not data.endswith(b"\xff\xd9"):
                    raise ValueError("Invalid JPEG dimensions or end marker")
                return {"format": "JPEG", "dimensions": [width, height], "container_checked": False, "pixels_decoded": False}
            offset += length
    raise ValueError("Unsupported or malformed image (use PNG or JPEG)")


def image_preflight(path, kind):
    source = RULES[kind]["source"]
    checks = []
    try:
        info = image_info(path.read_bytes())
    except (OSError, ValueError, zlib.error) as exc:
        return report(kind, [finding("image-container", "FAIL", str(exc), source)])
    dimensions = info["dimensions"]
    checks.append(finding("image-container", "PASS" if info["container_checked"] else "NOT_CHECKED", info, source))
    rule = RULES[kind]
    if "dimensions" in rule:
        checks.append(finding("template-dimensions", "PASS" if dimensions == rule["dimensions"] else "FAIL", {"actual": dimensions, "required": rule["dimensions"]}, source))
    if rule.get("square"):
        checks.append(finding("square-image", "PASS" if dimensions[0] == dimensions[1] else "FAIL", dimensions, source))
    if "max_texture_dimension" in rule:
        checks.append(finding("texture-dimensions", "PASS" if max(dimensions) <= rule["max_texture_dimension"] else "FAIL", dimensions, source))
    checks.append(finding("visual-panels-and-content", "NOT_CHECKED", "Inspect template panel placement, seams, transparency and content on target avatars.", source))
    return report(kind, checks, image=info)


def run_blender(path, kind, workflow, blender=None, output=None, objects=None, studs_per_unit=None, cage_baseline=None):
    executable = blender or shutil.which("blender")
    source = RULES[kind]["source"]
    if not executable:
        return report(kind, [finding("blender-runtime", "NOT_CHECKED", "Blender was not found. Install it or pass --blender PATH.", source)])
    config = {"input": str(path.resolve()), "kind": kind, "workflow": workflow,
              "output": str(output.resolve()) if output else None, "objects": objects,
              "studs_per_unit": studs_per_unit, "cage_baseline": str(cage_baseline.resolve()) if cage_baseline else None}
    with tempfile.TemporaryDirectory(prefix="roblox-ugc-") as temp:
        cfg = Path(temp) / "config.json"
        cfg.write_text(json.dumps(config))
        command = [executable, "--background", "--factory-startup", "--disable-autoexec", "--python",
                   str(Path(__file__).with_name("blender_worker.py")), "--", str(cfg)]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return report(kind, [finding("blender-runtime", "NOT_CHECKED", str(exc), source)])
    for line in reversed(process.stdout.splitlines()):
        if line.startswith("UGC_REPORT_JSON:"):
            result = json.loads(line.removeprefix("UGC_REPORT_JSON:"))
            result["blender_exit_code"] = process.returncode
            if process.returncode != 0:
                result["checks"].append(finding("blender-process", "FAIL", process.stderr[-1500:], source))
                result["blocking_failures"] += 1
            return result
    return report(kind, [finding("blender-analysis", "NOT_CHECKED", (process.stderr or process.stdout)[-2200:] or "No result returned", source)], blender_exit_code=process.returncode)


def preflight(path, kind, **kwargs):
    if not path.is_file():
        return report(kind, [finding("input-file", "FAIL", "File does not exist", RULES[kind]["source"])])
    if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        if kind not in ("classic-shirt", "classic-pants", "classic-tshirt", "makeup"):
            return report(kind, [finding("asset-format", "FAIL", "This category requires a 3D/animation project, not a standalone image", RULES[kind]["source"])])
        result = image_preflight(path, kind)
    elif path.suffix.lower() in (".blend", ".fbx", ".gltf", ".glb"):
        if kind.startswith("classic-"):
            result = report(kind, [finding("asset-format", "FAIL", "Classic clothing uses a 2D image workflow", RULES[kind]["source"])])
        else:
            result = run_blender(path, kind, **kwargs)
    else:
        result = report(kind, [finding("asset-format", "NOT_CHECKED", "Unsupported file format", RULES[kind]["source"])])
    result["input"] = str(path.resolve())
    result["input_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def prepare(kind, template, dest):
    registry = json.loads((SKILL / "assets/templates.json").read_text())
    item = next((r for r in registry if r["id"] == template), None)
    if not item or "sha256" not in item:
        raise ValueError("Unknown/unavailable template; run 'templates' to list verified downloads")
    if kind not in item["kinds"]:
        raise ValueError("Template does not match the selected asset kind")
    if dest.exists():
        raise ValueError("Destination exists; choose a new project directory")
    with urllib.request.urlopen(item["url"], timeout=45) as response:
        data = response.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Template size/checksum changed; review upstream before updating the registry")
    archive = zipfile.ZipFile(io.BytesIO(data))
    total = 0
    for member in archive.infolist():
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts or ":" in name or ((member.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError("Unsafe template archive member")
        total += member.file_size
    if total > 512 * 1024 * 1024:
        raise ValueError("Excessive expanded template size")
    # Stage all files before atomically making the project visible.
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ugc-prepare-", dir=dest.parent) as stage:
        project = Path(stage) / "project"
        for folder in ("source", "textures", "exports", "reports"):
            (project / folder).mkdir(parents=True, exist_ok=True)
        archive.extractall(project / "source")
        (project / "reports/template-provenance.json").write_text(json.dumps(item, indent=2) + "\n")
        (project / "CHECKLIST.md").write_text(f"# {kind} project\n\nTemplate: {item['source']}\n\n- Customize the source; template is a starting point.\n- Read the category workflow and preserve required rig/cage data.\n- Run preflight and export a copy.\n- Validate and fit in Studio.\n- Verify current publishing requirements and rights.\n")
        project.rename(dest)
    return {"project": str(dest.resolve()), "kind": kind, "template": template, "template_sha256": item["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("templates")
    p = subs.add_parser("prepare")
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--dest", type=Path, required=True)
    p = subs.add_parser("preflight")
    p.add_argument("asset", type=Path)
    for p in (p, subs.add_parser("export")):
        p.add_argument("--kind", choices=KINDS, required=True)
        p.add_argument("--workflow", choices=("traditional", "avatar-setup"), default="traditional")
        p.add_argument("--blender")
        p.add_argument("--objects", nargs="+")
        p.add_argument("--studs-per-unit", type=float)
        p.add_argument("--cage-baseline", type=Path, help="Official baseline .blend; cage topology/UV checks otherwise remain unvalidated")
        p.add_argument("--json", action="store_true", help="JSON is the default machine-readable output")
        p.add_argument("--report", type=Path)
    export = subs.choices["export"]
    export.add_argument("--input", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "templates":
            result = json.loads((SKILL / "assets/templates.json").read_text())
        elif args.command == "prepare":
            result = prepare(args.kind, args.template, args.dest)
        else:
            path = args.asset if args.command == "preflight" else args.input
            output = None
            if args.command == "export":
                output = args.output
                if output.exists() or output.resolve() == path.resolve():
                    raise ValueError("Export destination exists or matches the source; choose a new output")
                if path.suffix.lower() not in (".blend", ".fbx", ".gltf", ".glb") or output.suffix.lower() not in (".fbx", ".glb"):
                    raise ValueError("3D export supports .blend/.fbx/.gltf/.glb to a new .fbx or .glb")
            result = preflight(path, args.kind, workflow=args.workflow, blender=args.blender, output=output,
                objects=args.objects, studs_per_unit=args.studs_per_unit, cage_baseline=args.cage_baseline)
            if args.report:
                if args.report.resolve() == path.resolve():
                    raise ValueError("Report cannot overwrite the input")
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if isinstance(result, dict) and result.get("blocking_failures"):
            return 1
        if args.command == "export" and not result.get("exported"):
            return 2
        return 0
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
