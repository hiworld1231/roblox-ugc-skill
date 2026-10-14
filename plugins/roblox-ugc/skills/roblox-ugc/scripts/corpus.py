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
