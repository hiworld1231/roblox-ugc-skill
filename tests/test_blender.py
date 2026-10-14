from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
import unittest
import shutil

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/roblox-ugc/skills/roblox-ugc"
spec = importlib.util.spec_from_file_location("asset", SKILL / "scripts/asset.py")
asset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asset)


@unittest.skipUnless(shutil.which("blender"), "Blender not installed; integration tests explicitly skipped")
class BlenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ugc-blender-tests-")
        cls.dest = Path(cls.temp.name)
        subprocess.run([shutil.which("blender"), "--background", "--factory-startup", "--disable-autoexec", "--python", str(ROOT / "tests/blender_fixtures.py"), "--", str(cls.dest)], check=True, capture_output=True, timeout=90)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, name, kind="rigid", **kwargs):
        return asset.preflight(self.dest / (name + ".blend"), kind, workflow="traditional", **kwargs)

    def test_valid_rigid_has_geometry_evidence(self):
        result = self.check("valid-rigid")
        self.assertEqual(result["blocking_failures"], 0, result)
        self.assertEqual(result["metrics"][0]["triangles"], 12)
        self.assertIn("NOT_CHECKED", [r["status"] for r in result["checks"]])

    def test_multiple_render_meshes_fail(self):
        self.assertGreater(self.check("multiple-meshes")["blocking_failures"], 0)

    def test_holes_fail(self):
        self.assertGreater(self.check("open-rigid")["blocking_failures"], 0)

    def test_triangles_counted_after_triangulation(self):
        self.assertGreater(self.check("over-budget")["blocking_failures"], 0)

    def test_rigid_deform_modifier_fails(self):
        self.assertGreater(self.check("skinned-rigid")["blocking_failures"], 0)

    def test_missing_cages_fail(self):
        self.assertGreater(self.check("missing-layered-cages", "layered")["blocking_failures"], 0)

    def test_missing_body_and_facs_fail(self):
        result = self.check("missing-body-parts-and-facs", "body")
        self.assertTrue(any(r["check"] == "body-part-names" and r["status"] == "FAIL" for r in result["checks"]))
        self.assertTrue(any(r["check"] == "facs-pose-declarations" and r["status"] == "FAIL" for r in result["checks"]))

    def test_cage_uv_change_detected(self):
        result = self.check("changed-cage-uv", "layered", cage_baseline=self.dest / "cage-baseline.blend")
        self.assertTrue(any("cage-topology-uv" in r["check"] and r["status"] == "FAIL" for r in result["checks"]), result)

    def test_animation_does_not_require_render_mesh(self):
        result = self.check("animation-rig-only", "emote")
        self.assertFalse(any(r["check"] == "render-geometry-present" for r in result["checks"]), result)
        self.assertEqual(result["blocking_failures"], 0, result)

    def test_unbound_head_is_not_a_valid_rig(self):
        result = self.check("unbound-head", "head")
        self.assertTrue(any(r["check"].endswith(":skinning") and r["status"] == "FAIL" for r in result["checks"]), result)

    def test_export_real_fbx_and_source_unchanged(self):
        source = self.dest / "valid-rigid.blend"
        before = source.read_bytes()
        output = self.dest / "validated.fbx"
        result = self.check("valid-rigid", output=output)
        self.assertTrue(result.get("exported"), result)
        self.assertTrue(output.read_bytes().startswith(b"Kaydara FBX Binary"))
        self.assertEqual(source.read_bytes(), before)
        imported = asset.preflight(output, "rigid", workflow="traditional")
        self.assertEqual(imported["metrics"][0]["triangles"], 12)


if __name__ == "__main__":
    unittest.main()
