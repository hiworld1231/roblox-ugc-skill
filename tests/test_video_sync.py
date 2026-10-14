"""Review provenance survives source-link removal and restoration."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/roblox-ugc/skills/roblox-ugc/scripts/sync_corpus.py"
spec = importlib.util.spec_from_file_location("ugc_sync_review", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
VIDEO_ID = "Eed29gV0hLA"


def discovered(backlink="avatar/current"):
    return {"id": VIDEO_ID, "url": "https://www.youtube.com/watch?v=" + VIDEO_ID,
            "linked_by_official_docs": True, "backlinks": [backlink],
            "transcript_status": "not_reviewed", "visual_status": "not_reviewed"}


def reviewed():
    video = discovered("avatar/old")
    video.update(transcript_status="reviewed", visual_status="sampled",
                 transcript_sha256="a" * 64, reviewed_at="2026-10-14T00:00:00+00:00",
                 review_notes=["Original technique analysis."],
                 visual_samples=[{"seconds": 80, "observation": "A relevant UI control."}],
                 last_linked_revision="previous-commit")
    return video


class ReviewPreservationTests(unittest.TestCase):
    def test_current_analysis_retained_with_fresh_backlinks(self):
        current, archived, changes = sync.preserve_video_reviews(
            {VIDEO_ID: discovered()}, {VIDEO_ID: reviewed()}, {})
        self.assertEqual(current[VIDEO_ID]["review_notes"], reviewed()["review_notes"])
        self.assertEqual(current[VIDEO_ID]["transcript_sha256"], "a" * 64)
        self.assertEqual(current[VIDEO_ID]["visual_samples"], reviewed()["visual_samples"])
        self.assertEqual(current[VIDEO_ID]["backlinks"], ["avatar/current"])
        self.assertEqual(archived, {})
        self.assertEqual(changes, {"video_added": [], "video_removed": []})

    def test_removed_review_is_archived_without_current_coverage(self):
        current, archived, changes = sync.preserve_video_reviews({}, {VIDEO_ID: reviewed()}, {})
        self.assertEqual(current, {})
        self.assertEqual(changes["video_removed"], [VIDEO_ID])
        video = archived[VIDEO_ID]
        self.assertEqual(video["transcript_sha256"], "a" * 64)
        self.assertEqual(video["review_notes"], reviewed()["review_notes"])
        self.assertEqual(video["backlinks"], ["avatar/old"])
        self.assertFalse(video["linked_by_official_docs"])
        self.assertTrue(video["previously_linked_by_official_docs"])
        self.assertEqual(video["retired_from_revision"], "previous-commit")
        self.assertTrue(video["retired_at"])
        self.assertIn("historical", video["retirement_reason"])

    def test_restored_video_recovers_review_and_leaves_archive(self):
        _, retired, _ = sync.preserve_video_reviews({}, {VIDEO_ID: reviewed()}, {})
        current, retired, changes = sync.preserve_video_reviews(
            {VIDEO_ID: discovered("avatar/restored")}, {}, retired)
        self.assertEqual(changes["video_added"], [VIDEO_ID])
        self.assertEqual(retired, {})
        video = current[VIDEO_ID]
        self.assertEqual(video["transcript_status"], "reviewed")
        self.assertEqual(video["visual_status"], "sampled")
        self.assertEqual(video["backlinks"], ["avatar/restored"])
        self.assertTrue(video["linked_by_official_docs"])
        self.assertEqual(video["current_link_status"], "current")
        self.assertNotIn("retired_at", video)
        self.assertNotIn("retirement_reason", video)

    def test_repeated_sync_preserves_retirement_date(self):
        _, retired, _ = sync.preserve_video_reviews({}, {VIDEO_ID: reviewed()}, {})
        _, repeated, changes = sync.preserve_video_reviews({}, {}, retired)
        self.assertEqual(repeated, retired)
        self.assertEqual(changes, {"video_added": [], "video_removed": []})

    def test_merge_does_not_mutate_input_review_lists(self):
        prior = {VIDEO_ID: reviewed()}
        current, _, _ = sync.preserve_video_reviews({VIDEO_ID: discovered()}, prior, {})
        current[VIDEO_ID]["review_notes"].append("New note")
        current[VIDEO_ID]["visual_samples"][0]["seconds"] = 99
        self.assertEqual(prior[VIDEO_ID], reviewed())

    def test_active_record_wins_over_stale_archive_duplicate(self):
        old = reviewed()
        old["review_notes"] = ["Stale archive"]
        current, retired, _ = sync.preserve_video_reviews(
            {VIDEO_ID: discovered()}, {VIDEO_ID: reviewed()}, {VIDEO_ID: old})
        self.assertEqual(current[VIDEO_ID]["review_notes"], reviewed()["review_notes"])
        self.assertEqual(retired, {})

    def test_full_sync_mock_removes_and_restores_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skill"
            skill.mkdir()
            generation = [1]

            def fetch(url):
                if "/commits/" in url:
                    return json.dumps({"sha": str(generation[0]) * 40}).encode()
                if "/git/trees/" in url:
                    return json.dumps({"truncated": False, "tree": [{
                        "path": "content/en-us/avatar/demo.md", "type": "blob",
                        "sha": "blob" + str(generation[0]),
                    }]}).encode()
                if url.endswith("/docs/llms.txt"):
                    return b"[Demo](/docs/en-us/avatar/demo.md)"
                if url.endswith("avatar/demo.md"):
                    text = "# Demo\n"
                    if generation[0] != 2:
                        text += "https://www.youtube.com/watch?v=" + VIDEO_ID
                    return text.encode()
                if url.endswith(("/LICENSE", "/LICENSE-CODE")):
                    return b"Example fixture license"
                raise AssertionError("Unexpected external fetch: " + url)

            with patch.object(sync, "SKILL", skill), patch.object(sync, "fetch", fetch), \
                    patch.object(sys, "argv", ["sync_corpus.py"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sync.main(), 0)
                corpus = skill / "corpus"
                (corpus / "videos.json").write_text(json.dumps([reviewed()]))
                generation[0] = 2
                self.assertEqual(sync.main(), 0)
                self.assertEqual(json.loads((corpus / "videos.json").read_text()), [])
                retired = json.loads((corpus / "retired-videos.json").read_text())
                self.assertEqual(retired[0]["transcript_sha256"], "a" * 64)
                changes = json.loads((corpus / "changes.json").read_text())
                self.assertEqual(changes["video_removed"], [VIDEO_ID])
                self.assertEqual(json.loads((corpus / "coverage.json").read_text())["videos_indexed"], 0)
                generation[0] = 3
                self.assertEqual(sync.main(), 0)
                restored = json.loads((corpus / "videos.json").read_text())
                self.assertEqual(restored[0]["review_notes"], reviewed()["review_notes"])
                self.assertEqual(restored[0]["last_linked_revision"], "3" * 40)
                self.assertEqual(json.loads((corpus / "retired-videos.json").read_text()), [])
                changes = json.loads((corpus / "changes.json").read_text())
                self.assertEqual(changes["video_added"], [VIDEO_ID])


if __name__ == "__main__":
    unittest.main()
