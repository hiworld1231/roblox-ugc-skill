from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/roblox-ugc/skills/roblox-ugc"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / f"scripts/{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


asset = module("asset")
corpus = module("corpus")
sync = module("sync_corpus")


def png(width, height):
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    pixels = (b"\0" + b"\x80\x40\x20\xff" * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


class ImageTests(unittest.TestCase):
    def check(self, data, kind):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "image.png"
            path.write_bytes(data)
            return asset.preflight(path, kind)

    def test_shirt_valid_dimensions(self):
        result = self.check(png(585, 559), "classic-shirt")
        self.assertEqual(result["blocking_failures"], 0)
        self.assertTrue(result["requires_studio_validation"])
        self.assertFalse(result["marketplace_approved"])
        self.assertIn("NOT_CHECKED", [r["status"] for r in result["checks"]])

    def test_shirt_wrong_dimensions(self):
        self.assertGreater(self.check(png(512, 512), "classic-shirt")["blocking_failures"], 0)

    def test_tshirt_not_square(self):
        self.assertGreater(self.check(png(585, 559), "classic-tshirt")["blocking_failures"], 0)

    def test_makeup_over_budget(self):
        self.assertGreater(self.check(png(1025, 12), "makeup")["blocking_failures"], 0)

    def test_makeup_valid_budget(self):
        self.assertEqual(self.check(png(1024, 16), "makeup")["blocking_failures"], 0)

    def test_truncated_image(self):
        self.assertGreater(self.check(png(585, 559)[:-20], "classic-shirt")["blocking_failures"], 0)

    def test_corrupt_crc(self):
        data = bytearray(png(585, 559))
        data[25] ^= 1
        self.assertGreater(self.check(data, "classic-shirt")["blocking_failures"], 0)

    def test_image_cannot_be_rigid_asset(self):
        self.assertGreater(self.check(png(64, 64), "rigid")["blocking_failures"], 0)

    def test_missing_asset_is_failure(self):
        result = asset.preflight(Path("/tmp/no-such-ugc-asset-test-file"), "rigid")
        self.assertGreater(result["blocking_failures"], 0)

    def test_missing_blender_is_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.blend"
            path.write_bytes(b"not-a-blend")
            result = asset.preflight(path, "rigid", workflow="traditional", blender="/nonexistent/blender")
            self.assertEqual(result["checks"][0]["status"], "NOT_CHECKED")
            self.assertFalse(result.get("exported", False))

    def test_unknown_format_is_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.bin"
            path.write_bytes(b"unknown")
            self.assertEqual(asset.preflight(path, "rigid")["checks"][0]["status"], "NOT_CHECKED")

    def test_prepare_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "Destination exists"):
                asset.prepare("classic-shirt", "classic-clothing", Path(temp))


class CorpusTests(unittest.TestCase):
    def fixture(self, base):
        root = base / "corpus"
        root.mkdir()
        doc = root / "doc.md"
        doc.write_text("Actual document")
        record = {"id": "avatar/test", "status": "included", "reason": "Fixture", "local_path": "corpus/doc.md", "sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}
        (root / "sources.jsonl").write_text(json.dumps(record) + "\n")
        (root / "coverage.json").write_text(json.dumps({"counts": {"included": 1}, "revision": "test", "retrieved_at": "test", "videos_indexed": 0, "videos_transcripts_reviewed": 0, "videos_visuals_reviewed": 0, "unresolved_links": [], "unresolved_api_identifiers": [], "unprocessed_candidates": 0}))
        return root, doc, record

    def test_real_snapshot_integrity(self):
        self.assertTrue(corpus.audit()["ok"])

    def test_mutated_document_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, doc, _ = self.fixture(Path(temp))
            doc.write_text("Changed")
            self.assertFalse(corpus.audit(root)["ok"])

    def test_missing_document_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, doc, _ = self.fixture(Path(temp))
            doc.unlink()
            self.assertFalse(corpus.audit(root)["ok"])

    def test_duplicate_source_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, record = self.fixture(Path(temp))
            with (root / "sources.jsonl").open("a") as file:
                file.write(json.dumps(record) + "\n")
            self.assertFalse(corpus.audit(root)["ok"])

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            corpus.contained("../outside")

    def test_search_retrieves_actual_category(self):
        results = corpus.search("TransferTexture makeup", limit=8)
        self.assertTrue(any("makeup" in r["id"] for r in results))
        self.assertTrue(all(Path(r["path"]).is_file() for r in results))

    def test_index_alias_normalization(self):
        self.assertEqual(sync.key_for("/docs/en-us/avatar/index.md#body"), "avatar")

    def test_avatar_outside_root_included(self):
        self.assertTrue(sync.classify("production/monetization/avatar-items")[0])

    def test_creator_store_excluded(self):
        self.assertFalse(sync.classify("production/creator-store")[0])

    def test_audio_excluded(self):
        self.assertFalse(sync.classify("art/reaper")[0])

    def test_studio_mcp_is_creation_dependency(self):
        self.assertTrue(sync.classify("studio/mcp")[0])

    def test_video_review_search_keeps_evidence_boundaries(self):
        results = corpus.search("cryptic incorrect scale", topic="body", limit=100)
        videos = [r for r in results if r["id"].startswith("video/")]
        self.assertTrue(videos)
        self.assertTrue(all("transcript_status" in r and "visual_status" in r for r in videos))

    def test_reviewed_video_without_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _ = self.fixture(Path(temp))
            coverage = json.loads((root / "coverage.json").read_text())
            coverage.update(videos_indexed=1, videos_transcripts_reviewed=1)
            (root / "coverage.json").write_text(json.dumps(coverage))
            (root / "videos.json").write_text(json.dumps([{"id": "test", "transcript_status": "reviewed", "visual_status": "NOT_CHECKED"}]))
            self.assertFalse(corpus.audit(root)["ok"])

    def test_video_count_drift_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _ = self.fixture(Path(temp))
            (root / "videos.json").write_text(json.dumps([{"id": "test", "transcript_status": "unavailable", "visual_status": "sampled"}]))
            self.assertFalse(corpus.audit(root)["ok"])

    def test_community_review_without_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _ = self.fixture(Path(temp))
            (root / "community-videos.json").write_text(json.dumps([{"id": "community-test", "transcript_status": "reviewed", "visual_status": "reviewed"}]))
            result = corpus.audit(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("community-test" in p for p in result["problems"]))

    def test_sampled_frames_require_observation_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _, _ = self.fixture(Path(temp))
            (root / "community-videos.json").write_text(json.dumps([{"id": "sample", "transcript_status": "unavailable", "visual_status": "sampled", "visual_method": "Paused screenshots"}]))
            self.assertFalse(corpus.audit(root)["ok"])


if __name__ == "__main__":
    unittest.main()
