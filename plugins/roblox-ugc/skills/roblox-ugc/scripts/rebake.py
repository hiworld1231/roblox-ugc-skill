#!/usr/bin/env python3
"""Inspect materials or transfer their appearance to new UVs in an isolated Blender process."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BAKING_SOURCE = "https://docs.blender.org/manual/en/4.5/render/cycles/baking.html"
MAPS = ("base-color", "alpha", "roughness", "metallic", "normal")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)


def _digest(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(block)
    return result.hexdigest()


def result(check, status, evidence):
    return {"stage": "offline-texture-transfer", "checks": [{"check": check, "status": status,
            "evidence": evidence, "source": BAKING_SOURCE}], "blocking_failures": int(status == "FAIL"),
            "completed": False, "marketplace_approved": False}


def run(config, blender=None, timeout=300):
    """Public Python API. output is a NEW directory, never a source file or overwrite target."""
    config = dict(config)
    path = Path(config["input"]).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".blend":
        return result("input", "FAIL", "Use an existing .blend project with named source/target meshes.")
    output = Path(config["output"]).expanduser().resolve() if config.get("output") else None
    if config.get("mode", "rebake") == "rebake":
        if output is None or output.exists() or output == path or output in path.parents:
            return result("output", "FAIL", "Choose a new output directory; existing paths are never overwritten.")
        distance = config.get("ray_distance")
        if distance is None or distance <= 0:
            return result("projection", "FAIL", "Specify a positive ray_distance in the project's Blender units.")
        if config.get("remesh", "none") != "none" and config.get("target"):
            return result("remesh-target", "FAIL", "Remesh only a newly duplicated source; use a separately authored target unchanged.")
        if config.get("remesh", "none") != "none" and config.get("uv", "keep") != "smart":
            return result("remesh-uv", "FAIL", "Generated topology requires a new UV: use uv='smart'.")
        maps = config.get("maps", ["base-color", "alpha"])
        if not maps or set(maps) - set(MAPS) or len(set(maps)) != len(maps):
            return result("maps", "FAIL", "Choose unique explicit maps: " + ", ".join(MAPS))
        if not 16 <= config.get("size", 1024) <= 4096:
            return result("resolution", "FAIL", "Resolution must be between 16 and 4096; check Roblox's category/map limits separately.")
        sizes = config.get("map_sizes", {})
        if set(sizes) - set(MAPS) or any(not isinstance(v, int) or not 16 <= v <= 4096 for v in sizes.values()):
            return result("map-resolution", "FAIL", "Per-map sizes must use supported maps and integer sizes between 16 and 4096.")
        base_size = sizes.get("base-color", config.get("size", 1024))
        if sizes.get("alpha", base_size) != base_size:
            return result("alpha-resolution", "FAIL", "Alpha and Base Color must use matching dimensions for this helper.")
        if config.get("alpha_policy", "preserve") not in ("preserve", "opaque"):
            return result("alpha-policy", "FAIL", "Choose preserve or opaque.")
    executable = blender or shutil.which("blender")
    if not executable:
        return result("blender-runtime", "NOT_CHECKED", "Blender is unavailable; pass --blender PATH.")
    before = digest(path)
    config["input"] = str(path)
    if output:
        config["output"] = str(output)
    with tempfile.TemporaryDirectory(prefix="ugc-rebake-") as temp:
        cfg = Path(temp) / "config.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        command = [str(executable), "--background", "--factory-startup", "--disable-autoexec", "--python",
                   str(Path(__file__).with_name("blender_rebake_worker.py")), "--", str(cfg)]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report = result("blender-runtime", "FAIL", str(exc))
        else:
            report = None
            for line in reversed(process.stdout.splitlines()):
                if line.startswith("UGC_REBAKE_JSON:"):
                    try:
                        report = json.loads(line.removeprefix("UGC_REBAKE_JSON:"))
                    except json.JSONDecodeError:
                        pass
                    break
            if report is None:
                report = result("blender-result", "FAIL", (process.stderr or process.stdout)[-2500:])
            report["blender_exit_code"] = process.returncode
            if process.returncode and report["blocking_failures"] == 0:
                report["checks"].append({"check": "blender-process", "status": "FAIL", "evidence": process.stderr[-2000:], "source": BAKING_SOURCE})
                report["blocking_failures"] += 1
                report["completed"] = False
    after = digest(path)
    report["source_file"] = {"path": str(path), "sha256_before": before, "sha256_after": after, "unchanged": before == after}
    if before != after:
        report["checks"].append({"check": "source-preservation", "status": "FAIL", "evidence": "Input hash changed", "source": BAKING_SOURCE})
        report["blocking_failures"] += 1
        report["completed"] = False
    if output and output.is_dir():
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    inspect = sub.add_parser("inspect", help="Read source UVs, shader links, image provenance and transfer limitations")
    transfer = sub.add_parser("rebake", help="Copy the source or use an explicit target; write new images and project")
    for command in (inspect, transfer):
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--source", required=True, help="One named render mesh in the source .blend")
        command.add_argument("--blender", help="Blender executable (optional if in PATH)")
        command.add_argument("--report", type=Path, help="Additional new report file; never overwritten")
        command.add_argument("--timeout", type=int, default=300)
    transfer.add_argument("--target", help="Existing low mesh with its own UV; omitted means duplicate source")
    transfer.add_argument("--output", type=Path, required=True, help="NEW directory containing result.blend and textures")
    transfer.add_argument("--uv", choices=("keep", "smart"), default="keep")
    transfer.add_argument("--target-uv", help="Existing named UV layer when --uv keep; defaults to active render UV")
    transfer.add_argument("--source-uv", help="Source active render UV to use; explicit UV Map nodes retain their named mapping")
    transfer.add_argument("--maps", nargs="+", choices=MAPS, default=["base-color", "alpha"])
    transfer.add_argument("--size", type=int, default=1024)
    transfer.add_argument("--map-size", action="append", default=[], metavar="MAP=SIZE", help="Override a map size, e.g. normal=256; repeat for other maps")
    transfer.add_argument("--alpha-policy", choices=("preserve", "opaque"), default="preserve", help="Opaque requires opaque source alpha, then fills padding alpha; it never erases source transparency")
    transfer.add_argument("--margin", type=int, default=8, help="Bake dilation in pixels")
    transfer.add_argument("--ray-distance", type=float, required=True, help="Finite source projection distance in Blender units")
    transfer.add_argument("--cage", help="Named custom BAKE cage matching target topology; never a Roblox cage")
    transfer.add_argument("--cage-extrusion", type=float, default=0.0)
    transfer.add_argument("--remesh", choices=("none", "decimate", "voxel"), default="none")
    transfer.add_argument("--ratio", type=float, help="Explicit decimation ratio, greater than 0 and at most 1")
    transfer.add_argument("--voxel-size", type=float, help="Explicit voxel size in Blender units")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("--report already exists; choose a new file")
    config = vars(args).copy()
    for key in ("input", "output"):
        if config.get(key) is not None:
            config[key] = str(config[key])
    config.pop("report", None)
    config.pop("blender", None)
    config.pop("timeout", None)
    if "map_size" in config:
        config["map_sizes"] = {}
        try:
            for value in config.pop("map_size"):
                name, number = value.split("=", 1)
                if name in config["map_sizes"]:
                    raise ValueError("duplicate map")
                config["map_sizes"][name] = int(number)
        except ValueError:
            parser.error("Use unique --map-size MAP=INTEGER values")
    report = run(config, args.blender, args.timeout)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if report["blocking_failures"] else 0 if report.get("completed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
