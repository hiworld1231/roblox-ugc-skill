#!/usr/bin/env python3
"""Optional, isolated launcher for the upstream MCP for Blender bridge."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

VERSION = "2.1.9"
REVISION = "7a0373ec9199183cb460068c4f96aed9c579fb4f"
WHEEL_NAME = "mcp_for_blender-2.1.9-py3-none-any.whl"
WHEEL_URL = "https://files.pythonhosted.org/packages/e1/0b/53f520a143bd7b4cbb64d5311d29c8b51bab365bbbfd438a934006dc93a3/" + WHEEL_NAME
WHEEL_SHA256 = "a5cbc6cf316fa7433566eb505a0c26ca22e28c10083bd1b09a23d9e357821ccc"
ADDON_SHA256 = "eb0facf69781a30e69792532087d8d41c6a14fcd323353250abe7988ee297fa5"
LICENSE_SHA256 = "049501fd54d27852507853a5b88094ca1c6ff97404418a5032f3310eecc9cde6"
LOCK_SHA256 = "7001225c44fab1945cf8ea941e0e29c82d299d0b7f65796e2a282499ff743849"
DEFAULT_RUNTIME = Path.home() / ".cache" / "roblox-ugc" / ("blender-mcp-" + VERSION)
MAX_RESPONSE = 8 * 1024 * 1024


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_python(runtime):
    return Path(runtime) / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def check_port(port):
    if not 1024 <= int(port) <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    return int(port)


def request(command, params=None, *, port=9876, timeout=8):
    """One bounded read/write over the upstream local addon JSON protocol."""
    check_port(port)
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(json.dumps({"type": command, "params": params or {}}).encode())
        data = bytearray()
        while len(data) <= MAX_RESPONSE:
            chunk = conn.recv(min(65536, MAX_RESPONSE + 1 - len(data)))
            if not chunk:
                raise RuntimeError("Addon closed connection before a complete response")
            data.extend(chunk)
            try:
                response = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(response, dict):
                raise RuntimeError("Addon returned a non-object response")
            if response.get("status") != "success":
                raise RuntimeError("Addon error: " + str(response.get("message", "unknown")))
            return response.get("result", {})
    raise RuntimeError("Addon response exceeded 8 MiB")


def runtime_info(runtime):
    runtime = Path(runtime).resolve()
    problems = []
    for filename, expected in ((WHEEL_NAME, WHEEL_SHA256), ("addon.py", ADDON_SHA256), ("LICENSE.upstream", LICENSE_SHA256)):
        path = runtime / filename
        if not path.is_file():
            problems.append("Missing " + filename)
        elif digest(path) != expected:
            problems.append("Checksum mismatch: " + filename)
    if not runtime_python(runtime).is_file():
        problems.append("Missing isolated Python environment; run setup")
    state = runtime / "setup.json"
    if state.is_file():
        metadata = json.loads(state.read_text())
        if metadata.get("version") != VERSION or metadata.get("revision") != REVISION:
            problems.append("Runtime identity mismatch")
        lock = runtime / "requirements.lock"
        if not lock.is_file() or digest(lock) != LOCK_SHA256 or metadata.get("requirements_lock_sha256") != LOCK_SHA256:
            problems.append("Dependency lock checksum mismatch")
    else:
        problems.append("Missing setup.json")
    return {"ok": not problems, "runtime": str(runtime), "version": VERSION, "revision": REVISION, "problems": problems}


def run_checked(command):
    # Setup is a user-selected download/install action, never implicit in serve.
    subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)


def setup(runtime):
    runtime = Path(runtime).resolve()
    if (runtime / "setup.json").is_file():
        info = runtime_info(runtime)
        if not info["ok"]:
            raise RuntimeError("Existing runtime failed integrity checks: " + "; ".join(info["problems"]))
        return info
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is missing. Install it from https://docs.astral.sh/uv/getting-started/installation/")
    runtime.mkdir(parents=True, exist_ok=True)
    wheel = runtime / WHEEL_NAME
    if not wheel.is_file():
        with urllib.request.urlopen(WHEEL_URL, timeout=30) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != WHEEL_SHA256:
            raise RuntimeError("Upstream wheel checksum failed; no downloaded code was executed")
        wheel.write_bytes(data)
    if digest(wheel) != WHEEL_SHA256:
        raise RuntimeError("Cached upstream wheel checksum failed")
    # Extract only these exact members, never arbitrary archive paths.
    with zipfile.ZipFile(wheel) as archive:
        for member, name, expected in (
            ("blender_mcp/bundled/addon.py", "addon.py", ADDON_SHA256),
            ("mcp_for_blender-2.1.9.dist-info/licenses/LICENSE", "LICENSE.upstream", LICENSE_SHA256),
        ):
            data = archive.read(member)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("Pinned upstream member checksum mismatch: " + name)
            dest = runtime / name
            if dest.exists() and dest.read_bytes() != data:
                raise RuntimeError("Refusing to overwrite modified " + str(dest))
            dest.write_bytes(data)
    py = runtime_python(runtime)
    if not py.exists():
        run_checked([uv, "venv", "--python", "3.11", str(runtime / "venv")])
    pinned_lock = Path(__file__).with_name("blender_mcp_requirements.lock")
    if not pinned_lock.is_file() or digest(pinned_lock) != LOCK_SHA256:
        raise RuntimeError("Packaged dependency lock checksum failed")
    lock = runtime / "requirements.lock"
    if lock.exists() and lock.read_bytes() != pinned_lock.read_bytes():
        raise RuntimeError("Refusing to overwrite modified runtime dependency lock")
    lock.write_bytes(pinned_lock.read_bytes())
    run_checked([uv, "pip", "sync", "--python", str(py), "--require-hashes", str(lock)])
    installed = subprocess.check_output([str(py), "-c", "import importlib.metadata,json;print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))"], text=True)
    metadata = {"version": VERSION, "revision": REVISION, "wheel_sha256": WHEEL_SHA256,
                "addon_sha256": ADDON_SHA256, "license": "MIT", "reviewed_date": "2026-10-14",
                "requirements_lock_sha256": digest(lock), "dependencies": json.loads(installed)}
    (runtime / "setup.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return runtime_info(runtime)


def environment(runtime, port):
    env = os.environ.copy()
    # Ignore accidental remote settings and disable upstream data collection.
    env.update({"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": str(check_port(port)),
                "BLENDER_MCP_DISABLE_TELEMETRY": "1", "BLENDER_MCP_SAFE_MODE": "1",
                "UGC_BLENDER_RUNTIME": str(Path(runtime).resolve()), "UGC_BLENDER_PORT": str(port)})
    return env


def addon_info(port, timeout=8):
    info = request("get_addon_info", port=port, timeout=timeout)
    if not isinstance(info, dict) or info.get("name") != "MCP for Blender" or info.get("protocol_version") != 13:
        raise RuntimeError("Endpoint is not the expected MCP for Blender addon protocol 13")
    return info


BOOTSTRAP = '''import importlib.util, json, os, sys
from pathlib import Path
import bpy
runtime = Path(os.environ["UGC_BLENDER_RUNTIME"])
site = json.loads((runtime / "python-sites.json").read_text())
sys.path.extend(site)
spec = importlib.util.spec_from_file_location("ugc_blender_mcp_addon", runtime / "addon.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
bpy.context.scene.blendermcp_auto_start_server = False
bpy.context.scene.blendermcp_port = int(os.environ["UGC_BLENDER_PORT"])
bpy.context.scene["ugc_mcp_scratch"] = not bool(bpy.data.filepath)
bpy.context.scene["ugc_mcp_launch_nonce"] = os.environ["UGC_BLENDER_NONCE"]
server = addon.BlenderMCPServer(host="127.0.0.1", port=bpy.context.scene.blendermcp_port)
server.start()
bpy.types.UGC_isolated_mcp_server = server
print("UGC_MCP_READY" if server.running else "UGC_MCP_FAILED", flush=True)
'''


def launch(runtime, port=9876, blender=None, project=None, virtual_display=False):
    info = runtime_info(runtime)
    if not info["ok"]:
        raise RuntimeError("; ".join(info["problems"]))
    binary = shutil.which(blender or "blender")
    if not binary:
        raise RuntimeError("Blender is missing; pass --blender /absolute/path/to/blender")
    check_port(port)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError("Local port is already in use; select another --port") from None
    runtime = Path(runtime).resolve()
    if project:
        project = Path(project).resolve()
        if project.suffix.lower() != ".blend" or not project.is_file():
            raise ValueError("--project must name an existing .blend file")
    sites = subprocess.check_output([str(runtime_python(runtime)), "-c", "import site,json;print(json.dumps(site.getsitepackages()))"], text=True)
    (runtime / "python-sites.json").write_text(sites)
    script = runtime / "bootstrap.py"
    script.write_text(BOOTSTRAP)
    command = [binary, "--factory-startup", "--disable-autoexec"]
    if project:
        command.append(str(project))
    command += ["--python", str(script)]
    if virtual_display:
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            raise RuntimeError("xvfb-run is missing; launch a normal GUI or install Xvfb")
        command = [xvfb, "-a", "-s", "-screen 0 1280x1024x24"] + command
    logfile = runtime / f"blender-{port}.log"
    nonce = secrets.token_hex(16)
    env = environment(runtime, port)
    env["UGC_BLENDER_NONCE"] = nonce
    with logfile.open("ab") as stream:
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                   start_new_session=os.name != "nt",
                                   creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0)
    result = {"pid": process.pid, "port": port, "log": str(logfile), "scratch": not bool(project),
              "virtual_display": virtual_display, "status": "NOT_CHECKED", "source_saved": False}
    end = time.monotonic() + 25
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError("Blender exited before readiness; inspect " + str(logfile))
        try:
            result["addon"] = addon_info(port, timeout=1)
            result["status"] = "PASS"
            break
        except (OSError, RuntimeError):
            time.sleep(0.2)
    (runtime / f"launch-{port}.json").write_text(json.dumps({**result, "nonce": nonce}, indent=2) + "\n")
    return result


def stop(runtime, port):
    state = Path(runtime).resolve() / f"launch-{port}.json"
    if not state.is_file():
        raise RuntimeError("No launch record; refusing to close an unrelated Blender")
    launch_record = json.loads(state.read_text())
    nonce = launch_record.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 32:
        raise RuntimeError("Launch record has no ownership token")
    code = f'''import bpy
if bpy.context.scene.get("ugc_mcp_launch_nonce") != {nonce!r}:
    raise RuntimeError("Current Blender is not this launch; refusing to close it")
bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.3)
print("UGC_MCP_STOP_SCHEDULED")
'''
    result = request("execute_code", {"code": code}, port=port)
    if "UGC_MCP_STOP_SCHEDULED" not in result.get("result", ""):
        raise RuntimeError("Quit was not scheduled")
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if status(port)["status"] == "NOT_CHECKED":
            return {"status": "PASS", "port": port, "evidence": "Owned Blender quit; localhost endpoint closed"}
        time.sleep(0.2)
    return {"status": "WARN", "port": port, "reason": "Quit scheduled, but endpoint still responds"}


SMOKE_PROBE = '''import asyncio, base64, hashlib, json, pathlib, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
script, runtime, port, dest = sys.argv[1:]
dest = pathlib.Path(dest)
async def run():
    result = {"status": "FAIL", "checks": [], "files": {}}
    parameters = StdioServerParameters(command=sys.executable, args=[script, "serve", "--runtime", runtime, "--port", port])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            result["server"] = init.serverInfo.model_dump()
            catalog = await session.list_tools()
            names = [tool.name for tool in catalog.tools]
            result["tools"] = names
            required = {"get_scene_info", "execute_blender_code", "look"}
            if not required.issubset(names):
                raise RuntimeError("Required tools missing")
            result["checks"].append({"check": "MCP initialize and tools/list", "status": "PASS"})
            code = """import bpy
if bpy.data.filepath or not bpy.context.scene.get('ugc_mcp_scratch'):
    raise RuntimeError('Smoke test requires a fresh launcher scratch scene')
if bpy.data.objects.get('UGC_MCP_Probe'):
    raise RuntimeError('Smoke probe already exists')
bpy.ops.mesh.primitive_torus_add(major_segments=24, minor_segments=8, major_radius=1.0, minor_radius=0.2, location=(4.0, 0.0, 0.0))
obj = bpy.context.object
obj.name = 'UGC_MCP_Probe'
mat = bpy.data.materials.new('UGC_MCP_ProbeMaterial')
mat.diffuse_color = (0.04, 0.55, 0.8, 1.0)
obj.data.materials.append(mat)
obj.data.calc_loop_triangles()
print('UGC_MCP_CREATED', obj.name, len(obj.data.loop_triangles), len(obj.data.uv_layers))
"""
            created = await session.call_tool("execute_blender_code", {"code": code, "user_prompt": "Test the Roblox UGC Blender MCP launcher in its isolated scratch scene"})
            texts = [item.text for item in created.content if item.type == "text"]
            if created.isError or not any("UGC_MCP_CREATED" in text for text in texts):
                raise RuntimeError("Object creation failed: " + str(texts))
            result["checks"].append({"check": "MCP Python object creation", "status": "PASS", "response": texts})
            inspected = await session.call_tool("get_scene_info", {"query": "UGC_MCP_Probe", "fields": ["details", "topology", "materials"], "user_prompt": "Test the Roblox UGC Blender MCP launcher in its isolated scratch scene"})
            summary = [item.text for item in inspected.content if item.type == "text"]
            if inspected.isError or not any("UGC_MCP_Probe" in text for text in summary):
                raise RuntimeError("Created object was not observable")
            result["checks"].append({"check": "MCP scene observation", "status": "PASS", "response": summary})
            view = await session.call_tool("look", {"mode": "angles", "target": ["UGC_MCP_Probe"], "views": ["front", "top", "three_quarter"], "shading": "solid", "max_size": 900, "user_prompt": "Test the Roblox UGC Blender MCP launcher in its isolated scratch scene"})
            images = [item for item in view.content if item.type == "image"]
            if view.isError or not images:
                raise RuntimeError("MCP image unavailable: " + str(view.content))
            preview = dest / "mcp-preview.png"
            preview.write_bytes(base64.b64decode(images[0].data))
            if not preview.read_bytes().startswith(b'\\x89PNG\\r\\n\\x1a\\n'):
                raise RuntimeError("Preview is not PNG")
            result["checks"].append({"check": "MCP look image returned", "status": "PASS", "visual_review": "NOT_CHECKED"})
            project = dest / "mcp-probe.blend"
            saved = await session.call_tool("execute_blender_code", {"code": "import bpy\\nbpy.ops.wm.save_as_mainfile(filepath=" + repr(str(project)) + ", compress=False)\\nprint('UGC_MCP_SAVED')", "user_prompt": "Test the Roblox UGC Blender MCP launcher in its isolated scratch scene"})
            if saved.isError or not project.is_file() or not project.read_bytes().startswith(b'BLENDER'):
                raise RuntimeError("Scratch Blender file was not saved")
            result["checks"].append({"check": "MCP scratch project save", "status": "PASS"})
            rejected = await session.call_tool("execute_blender_code", {"code": "import os\\nprint(os.environ)", "user_prompt": "Test safe-mode rejection without printing environment values"})
            if rejected.isError or not any("Rejected by safe mode" in item.text for item in rejected.content if item.type == "text"):
                raise RuntimeError("Safe mode did not reject environment access")
            result["checks"].append({"check": "Safe-mode denied environment access", "status": "PASS"})
            for path in (preview, project):
                result["files"][path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    result["status"] = "PASS"
    result["limits"] = ["Scratch torus is a transport fixture, not a Marketplace asset", "ClientSession smoke does not verify Codex or Claude UI", "Preview must be visually inspected separately"]
    (dest / "mcp-validation.json").write_text(json.dumps(result, indent=2) + "\\n")
    print(json.dumps(result, indent=2))
asyncio.run(run())
'''


def smoke(runtime, port, dest):
    info = runtime_info(runtime)
    if not info["ok"]:
        raise RuntimeError("; ".join(info["problems"]))
    dest = Path(dest).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError("Smoke destination must be empty; existing results are preserved")
    dest.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([str(runtime_python(runtime)), "-c", SMOKE_PROBE, str(Path(__file__).resolve()),
                              str(Path(runtime).resolve()), str(port), str(dest)], env=environment(runtime, port),
                             capture_output=True, text=True, timeout=120)
    if process.returncode:
        (dest / "mcp-error.log").write_text(process.stderr)
        raise RuntimeError("MCP smoke failed; inspect " + str(dest / "mcp-error.log"))
    return json.loads(process.stdout)


def status(port):
    try:
        info = addon_info(port)
        return {"status": "PASS", "host": "127.0.0.1", "port": port, "addon": info,
                "evidence": "Actual addon protocol response; MCP client tools still need a client handshake"}
    except (OSError, RuntimeError) as error:
        return {"status": "NOT_CHECKED", "host": "127.0.0.1", "port": port, "reason": str(error)}


def config(runtime, port=9876):
    return {"mcpServers": {"blender-ugc": {"command": sys.executable,
        "args": [str(Path(__file__).resolve()), "serve", "--runtime", str(Path(runtime).resolve()), "--port", str(check_port(port))]}}}


def serve(runtime, port):
    info = runtime_info(runtime)
    if not info["ok"]:
        raise RuntimeError("; ".join(info["problems"]))
    py = str(runtime_python(Path(runtime).resolve()))
    # os.exec replaces this wrapper; stdout remains exclusively MCP stdio.
    os.execve(py, [py, "-c", "from blender_mcp.server import main; main()", "--host", "127.0.0.1", "--port", str(check_port(port))], environment(runtime, port))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "setup", "launch", "status", "config", "serve", "stop", "smoke"):
        sub = commands.add_parser(name)
        sub.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
        sub.add_argument("--port", type=int, default=9876)
        if name == "launch":
            sub.add_argument("--blender")
            sub.add_argument("--project", type=Path)
            sub.add_argument("--virtual-display", action="store_true")
        if name == "smoke":
            sub.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check_port(args.port)
        if args.command == "serve":
            serve(args.runtime, args.port)
            return 0
        if args.command == "setup":
            result = setup(args.runtime)
        elif args.command == "launch":
            result = launch(args.runtime, args.port, args.blender, args.project, args.virtual_display)
        elif args.command == "config":
            result = config(args.runtime, args.port)
        elif args.command == "status":
            result = status(args.port)
        elif args.command == "stop":
            result = stop(args.runtime, args.port)
        elif args.command == "smoke":
            result = smoke(args.runtime, args.port, args.dest)
        else:
            result = runtime_info(args.runtime)
            result.update({"blender": shutil.which("blender"), "uv": shutil.which("uv"), "connection": status(args.port),
                           "gui_required": True, "global_client_config_changed": False})
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", result.get("status") == "PASS" if "status" in result else True) else 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        # Do not dump the inherited environment, credentials or an upstream traceback.
        print(json.dumps({"status": "FAIL", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
