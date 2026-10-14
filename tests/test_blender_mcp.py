"""Launcher invariants; real GUI + MCP evidence is recorded separately."""
from pathlib import Path
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/roblox-ugc/skills/roblox-ugc/scripts/blender_mcp.py"
spec = importlib.util.spec_from_file_location("ugc_blender_mcp", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class LauncherTests(unittest.TestCase):
    def test_missing_runtime_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = bridge.runtime_info(tmp)
            self.assertFalse(info["ok"])
            self.assertGreaterEqual(len(info["problems"]), 4)

    def test_config_is_absolute_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = bridge.config(tmp, 19876)
            server = config["mcpServers"]["blender-ugc"]
            self.assertTrue(Path(server["command"]).is_absolute())
            self.assertEqual(server["args"][0], str(SCRIPT))
            self.assertEqual(server["args"][-1], "19876")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_invalid_ports_fail_before_network(self):
        for port in (0, -1, 1023, 65536):
            with self.assertRaises(ValueError):
                bridge.request("get_scene_info", port=port)

    def test_inherited_remote_and_telemetry_settings_are_overridden(self):
        with patch.dict(bridge.os.environ, {"BLENDER_HOST": "remote.example", "BLENDER_MCP_DISABLE_TELEMETRY": "0"}):
            env = bridge.environment("/tmp/ugc", 19876)
            self.assertEqual(env["BLENDER_HOST"], "127.0.0.1")
            self.assertEqual(env["BLENDER_PORT"], "19876")
            self.assertEqual(env["BLENDER_MCP_DISABLE_TELEMETRY"], "1")
            self.assertEqual(env["BLENDER_MCP_SAFE_MODE"], "1")

    def test_modified_wheel_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / bridge.WHEEL_NAME
            wheel.write_bytes(b"modified wheel")
            with patch.object(bridge.shutil, "which", return_value="uv"), patch.object(bridge, "run_checked") as run:
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    bridge.setup(tmp)
                run.assert_not_called()
            self.assertEqual(wheel.read_bytes(), b"modified wheel")

    def test_packaged_dependency_lock_is_complete(self):
        lock = SCRIPT.with_name("blender_mcp_requirements.lock")
        self.assertEqual(bridge.digest(lock), bridge.LOCK_SHA256)
        text = lock.read_text()
        self.assertIn("pywin32", text)
        self.assertIn("sys_platform == 'win32'", text)
        self.assertIn("mcp==1.30.0", text)

    def test_loopback_fragmented_protocol_response(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        received = []

        def respond():
            with server, server.accept()[0] as client:
                received.append(json.loads(client.recv(4096)))
                client.sendall(b'{"status":"success","result":')
                client.sendall(b'{"protocol_version":13}}')

        thread = threading.Thread(target=respond)
        thread.start()
        self.assertEqual(bridge.request("get_addon_info", port=port), {"protocol_version": 13})
        thread.join(2)
        self.assertEqual(received, [{"type": "get_addon_info", "params": {}}])

    def test_non_object_protocol_response_is_rejected(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def respond():
            with server, server.accept()[0] as client:
                client.recv(4096)
                client.sendall(b'[]')

        thread = threading.Thread(target=respond)
        thread.start()
        with self.assertRaisesRegex(RuntimeError, "non-object"):
            bridge.request("get_scene_info", port=port)
        thread.join(2)

    def test_absent_listener_is_not_checked(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            self.assertEqual(bridge.status(port)["status"], "NOT_CHECKED")

    def test_unrelated_endpoint_never_passes(self):
        with patch.object(bridge, "request", return_value={"name": "Other service", "protocol_version": 13}):
            self.assertEqual(bridge.status(19876)["status"], "NOT_CHECKED")

    def test_stop_refuses_unowned_runtime(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, "request") as network:
            with self.assertRaisesRegex(RuntimeError, "unrelated"):
                bridge.stop(tmp, 19876)
            network.assert_not_called()

    def test_smoke_does_not_overwrite_results(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, "runtime_info", return_value={"ok": True}):
            output = Path(tmp) / "existing.txt"
            output.write_text("retain")
            with self.assertRaisesRegex(RuntimeError, "empty"):
                bridge.smoke(tmp, 19876, tmp)
            self.assertEqual(output.read_text(), "retain")

    def test_bootstrap_preserves_files_and_user_preferences(self):
        self.assertIn('host="127.0.0.1"', bridge.BOOTSTRAP)
        self.assertIn("blendermcp_auto_start_server = False", bridge.BOOTSTRAP)
        self.assertNotIn("save_userpref", bridge.BOOTSTRAP)
        self.assertNotIn("save_as_mainfile", bridge.BOOTSTRAP)
        self.assertNotIn("addon_install", bridge.BOOTSTRAP)


if __name__ == "__main__":
    unittest.main()
