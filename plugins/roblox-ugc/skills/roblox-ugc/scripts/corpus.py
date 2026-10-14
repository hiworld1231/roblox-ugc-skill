#!/usr/bin/env python3
"""Search, inspect, verify and maintain the local Roblox UGC corpus (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CORPUS = SKILL / "corpus"


def records(root=CORPUS):
    return [json.loads(line) for line in (root / "sources.jsonl").read_text().splitlines() if line.strip()]


def contained(relative, root=SKILL):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path leaves the installed skill directory")
    return path


def search(query, topic=None, limit=10):
    terms = re.findall(r"[\w-]+", query.lower())
    if not terms:
        return []
    matches = []
    for record in records():
        if record["status"] != "included" or not record.get("local_path"):
            continue
        if topic and topic not in record["topics"]:
            continue
        text = contained(record["local_path"]).read_text()
        lower = text.lower()
        title = (record["id"] + " " + record["title"]).lower()
        matched = sum(t in lower or t in title for t in terms)
        if not matched:
            continue
        score = matched * 10 + sum(title.count(t) * 8 + min(lower.count(t), 15) for t in terms)
        lines = text.splitlines()
        snippets = [(i + 1, line.strip()[:260]) for i, line in enumerate(lines)
                    if any(t in line.lower() for t in terms)][:3]
        matches.append({"id": record["id"], "title": record["title"], "score": score,
            "path": str(contained(record["local_path"])), "url": record["canonical_url"],
            "retrieved_at": record["retrieved_at"], "topics": record["topics"], "snippets": snippets})
    for filename, prefix in (("videos.json", "video/"), ("community-videos.json", "community-video/"), ("retired-videos.json", "retired-video/")):
        video_file = CORPUS / filename
        if not video_file.exists():
            continue
        for video in json.loads(video_file.read_text()):
            if video.get("scope") == "excluded" or not video.get("review_notes"):
                continue
            if topic and topic not in video.get("topics", []):
                continue
            notes = video["review_notes"]
            title = video.get("title", video["id"])
            lower = (title + " " + " ".join(notes)).lower()
            matched = sum(t in lower for t in terms)
            if matched:
                matches.append({"id": prefix + video["id"], "title": title,
                    "score": matched * 10 + sum(title.lower().count(t) * 8 for t in terms),
                    "path": str(video_file), "url": video["url"],
                    "retrieved_at": video.get("reviewed_at"), "topics": video.get("topics", []),
                    "transcript_status": video["transcript_status"], "visual_status": video["visual_status"],
                    "source_status": "retired" if filename == "retired-videos.json" else "current",
                    "snippets": [(i + 1, note) for i, note in enumerate(notes)
                                 if any(t in note.lower() for t in terms)][:3]})
    reference_topics = {
        "rigid": ["rigid"], "layered": ["layered"], "bodies-heads": ["body", "head"],
        "classic-makeup": ["classic", "makeup"], "animations": ["animation"],
        "publishing": ["publishing"], "studio-api": ["studio"], "studio-control": ["studio"],
        "authoring": ["pipeline", "authoring"], "blender-mcp": ["pipeline", "authoring"],
        "rbx-toolbox": ["pipeline", "authoring"], "remesh-rebake": ["pipeline", "authoring"],
        "community": ["pipeline"], "sources": ["pipeline"], "troubleshooting": ["pipeline"],
    }
    for path in (SKILL / "references").glob("*.md"):
        tags = reference_topics.get(path.stem, ["pipeline"])
        if topic and topic not in tags:
            continue
        lines = path.read_text().splitlines()
        title = lines[0].removeprefix("# ") if lines else path.stem
        lower = "\n".join(lines).lower()
        matched = sum(t in lower for t in terms)
        if matched:
            matches.append({"id": "guide/" + path.stem, "title": title,
                "score": matched * 10 + sum(title.lower().count(t) * 8 + min(lower.count(t), 15) for t in terms),
                "path": str(path), "url": "https://github.com/hiworld1231/roblox-ugc-skill/blob/main/plugins/roblox-ugc/skills/roblox-ugc/references/" + path.name,
                "source_type": "authored_reference", "retrieved_at": "See cited source snapshot and integration records", "topics": tags,
                "snippets": [(i + 1, line.strip()[:260]) for i, line in enumerate(lines)
                             if any(t in line.lower() for t in terms)][:3]})
    return sorted(matches, key=lambda r: (-r["score"], r["id"]))[:limit]


def audit(root=CORPUS, live=False):
    problems = []
    recs = records(root)
    seen = set()
    for rec in recs:
        if rec["id"] in seen:
            problems.append("Duplicate source id: " + rec["id"])
        seen.add(rec["id"])
        if rec["status"] not in ("included", "excluded", "superseded") or not rec.get("reason"):
            problems.append("Unclassified source: " + rec["id"])
        if rec["status"] != "included":
            continue
        if not rec.get("local_path"):
            problems.append("Missing local source: " + rec["id"])
            continue
        try:
            path = contained(rec["local_path"], root.parent)
            data = path.read_bytes()
            expected = rec.get("local_sha256", rec.get("sha256"))
            if hashlib.sha256(data).hexdigest() != expected:
                problems.append("Checksum mismatch: " + rec["id"])
        except (ValueError, OSError) as exc:
            problems.append(rec["id"] + ": " + str(exc))
    coverage = json.loads((root / "coverage.json").read_text())
    if coverage.get("upstream_tree_truncated") or coverage.get("unprocessed_candidates"):
        problems.append("Incomplete inventory")
    included = sum(r["status"] == "included" for r in recs)
    if coverage["counts"]["included"] != included:
        problems.append("Coverage count mismatch")
    for filename in ("videos.json", "community-videos.json", "retired-videos.json"):
        video_file = root / filename
        if not video_file.exists():
            if filename == "videos.json" and coverage["videos_indexed"]:
                problems.append("Missing official video inventory")
            continue
        videos = json.loads(video_file.read_text())
        if len({v["id"] for v in videos}) != len(videos):
            problems.append("Duplicate video id: " + filename)
        if filename == "videos.json":
            for field, count_field in ((None, "videos_indexed"), ("transcript_status", "videos_transcripts_reviewed"), ("visual_status", "videos_visuals_reviewed")):
                actual = len(videos) if field is None else sum(v.get(field) == "reviewed" for v in videos)
                if coverage[count_field] != actual:
                    problems.append("Video coverage count mismatch: " + count_field)
            if "videos_visuals_sampled" in coverage and coverage["videos_visuals_sampled"] != sum(v.get("visual_status") == "sampled" for v in videos):
                problems.append("Video coverage count mismatch: videos_visuals_sampled")
        for video in videos:
            if video.get("transcript_status") == "reviewed" and (not all(video.get(k) for k in ("review_notes", "reviewed_at", "transcript_sha256")) or not re.fullmatch(r"[0-9a-f]{64}", video.get("transcript_sha256", ""))):
                problems.append("Missing transcript review provenance: " + video["id"])
            if video.get("visual_status") == "reviewed" and not video.get("full_visual_review_evidence"):
                problems.append("Missing full visual review evidence: " + video["id"])
            if video.get("visual_status") == "sampled":
                times = video.get("visual_sample_times")
                if not video.get("visual_method") or not isinstance(times, list) or not times or not all(type(t) in (int, float) and t >= 0 for t in times):
                    problems.append("Missing sampled visual provenance: " + video["id"])
    result = {"ok": not problems, "problems": problems, "sources": len(recs), "included": included,
              "revision": coverage["revision"], "retrieved_at": coverage["retrieved_at"],
              "videos": {"indexed": coverage["videos_indexed"], "transcripts_reviewed": coverage["videos_transcripts_reviewed"],
                         "visuals_reviewed": coverage["videos_visuals_reviewed"]},
              "source_defects": len(coverage["unresolved_links"]) + len(coverage["unresolved_api_identifiers"])}
    if live:
        try:
            with urllib.request.urlopen("https://create.roblox.com/docs/llms.txt", timeout=30) as response:
                digest = hashlib.sha256(response.read()).hexdigest()
            result["live_inventory_changed"] = digest != coverage["inventory_sha256"]
            result["live_notice"] = "An unchanged index does not prove unchanged prices, policies or page contents. Recheck the specific live source."
        except OSError as exc:
            result["live_status"] = "NOT_CHECKED"
            result["live_error"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("search")
    p.add_argument("query")
    p.add_argument("--topic")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p = subs.add_parser("show")
    p.add_argument("source_id")
    p.add_argument("--start-line", type=int, default=1)
    p.add_argument("--lines", type=int, default=120)
    p = subs.add_parser("audit")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p = subs.add_parser("sync", help="Maintenance only: updates files, then requires review of authored rules")
    p.add_argument("--revision", default="main")
    args = parser.parse_args()
    if args.command == "search":
        result = search(args.query, args.topic, args.limit)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            for item in result:
                print(f"{item['id']} — {item['url']}\n  {item['path']} ({item['retrieved_at']})")
                for number, line in item["snippets"]:
                    print(f"  L{number}: {line}")
        return 0
    if args.command == "show":
        if args.source_id.startswith("guide/"):
            path = contained("references/" + args.source_id.removeprefix("guide/") + ".md")
            if not path.is_file():
                print("Unknown guide id", file=sys.stderr)
                return 1
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines, 1):
                if args.start_line <= i < args.start_line + args.lines:
                    print(f"{i}: {line}")
            return 0
        if args.source_id.startswith(("video/", "community-video/", "retired-video/")):
            prefix, video_id = args.source_id.split("/", 1)
            filename = {"video": "videos.json", "community-video": "community-videos.json", "retired-video": "retired-videos.json"}[prefix]
            path = CORPUS / filename
            video = next((v for v in json.loads(path.read_text())
                          if v["id"] == video_id), None)
            if video is None:
                print("Unknown video id", file=sys.stderr)
                return 1
            print(json.dumps(video, indent=2, ensure_ascii=False))
            return 0
        rec = next((r for r in records() if r["id"] == args.source_id), None)
        if not rec or not rec.get("local_path"):
            parser.error("No local included source with that id; use search first")
        lines = contained(rec["local_path"]).read_text().splitlines()
        start = max(0, args.start_line - 1)
        print(f"Source: {rec['canonical_url']} | revision: {rec.get('source_revision')} | retrieved: {rec['retrieved_at']}")
        for i in range(start, min(len(lines), start + max(1, args.lines))):
            print(f"{i+1}: {lines[i]}")
        return 0
    if args.command == "audit":
        result = audit(live=args.live)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1
    if args.command == "sync":
        print("Updating the source snapshot. Review changed rules, curated references, and video metadata before releasing.", file=sys.stderr)
        return subprocess.call([sys.executable, str(Path(__file__).with_name("sync_corpus.py")), "--revision", args.revision])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
