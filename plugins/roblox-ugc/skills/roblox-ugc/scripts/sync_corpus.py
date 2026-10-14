#!/usr/bin/env python3
"""Reproduce the scoped Roblox documentation inventory and licensed snapshots."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import posixpath
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
DOCS = "https://create.roblox.com"
REPO = "https://api.github.com/repos/Roblox/creator-docs"
EXPLICIT = {
    "monetize-avatar", "studio/importer", "studio/avatar-settings",
    "studio/testing-modes", "studio/rig-builder", "studio/animation-editor", "studio/mcp",
    "players/avatar-editor", "players/avatar-inspect-menu", "players/avatar-context-menu",
    "characters/appearance", "characters/emotes", "characters/adaptive-animation",
    "characters/r6-to-r15-adapter", "projects/assets", "projects/assets/manager",
    "projects/assets/privacy", "projects/assets/packages", "projects/groups",
    "parts/meshes", "parts/textures-decals", "parts/model-generation",
    "cloud/guides/usage-assets", "cloud/guides/assets", "cloud/open-cloud",
    "cloud/auth/api-keys", "cloud/auth/oauth2", "cloud/reference/patterns",
    "production/monetization/avatar-items", "production/monetization/avatar-creation-token",
    "production/monetization/regional-pricing", "production/monetization/developer-exchange",
    "production/publishing/account-verification", "production/publishing/id-verification",
    "production/publishing/intellectual-property", "production/publishing/rights-manager",
    "creator-programs/todays-picks-marketplace", "workspace/cframes", "physics/units",
    "production/publishing/ip-guidelines", "ip-licensing/creators", "ip-licensing/get-started",
    "production/monetization/roblox-plus", "production/monetization/18-plus-devex-rate",
    "production/promotion/ads-manager", "production/promotion/advertise",
    "production/analytics/analytics-dashboard", "studio/texture-generator",
    "tutorials/use-case-tutorials/animation/create-an-animation",
    "cloud/auth/oauth2-overview", "cloud/auth/oauth2-registration", "cloud/reference/scopes",
}
API_CLASSES = {
    "Accessory", "AccessoryDescription", "Attachment", "AvatarCreationService",
    "AvatarEditorService", "BodyColors", "BodyPartDescription", "Bone", "CatalogPages",
    "Decal", "DigitsRigDescription", "FaceControls", "Humanoid", "HumanoidDescription",
    "HumanoidRigDescription", "InsertService", "MarketplaceService", "MeshPart",
    "Model", "Pants", "Player", "Players", "Shirt", "ShirtGraphic", "SurfaceAppearance",
    "WrapLayer", "WrapTarget", "WrapTextureTransfer", "Animator", "Animation",
    "AnimationController", "AnimationRigData", "CurveAnimation", "KeyframeSequence",
    "ContentProvider", "HiddenSurfaceRemovalAsset", "EditableImage", "EditableMesh",
    "AssetService", "Selection", "HttpService", "RunService", "Folder",
}


def fetch(url: str) -> bytes:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "roblox-ugc-skill/0.1.0", "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404):
                raise
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError(url)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_for(path: str) -> str:
    path = urllib.parse.unquote(path).split("#")[0].split("?")[0]
    path = re.sub(r"^/docs/(?:en-us/)?", "", path)
    path = re.sub(r"\.(?:md|yaml)$", "", path)
    return path.removesuffix("/index").strip("/")


def classify(key: str) -> tuple[bool, str]:
    if key == "art/reaper" or key.startswith("art/audio"):
        return False, "Audio production is outside Marketplace avatar creation."
    if key in ("avatar", "avatar-setup", "marketplace", "art") or key.startswith(("avatar/", "avatar-setup/", "marketplace/", "art/")):
        return True, "Avatar/Marketplace creation, specifications, tutorials, or DCC dependency."
    if key.startswith(("animation/", "cloud/legacy/avatar/")) or key == "animation":
        return True, "Avatar animation authoring or related avatar REST API documentation."
    if key in EXPLICIT:
        return True, "Explicit creation, commerce, authentication, or avatar integration dependency."
    if re.search(r"(?:avatar|ugc|marketplace|classic-clothing|layered-clothing|dynamic-head|facial-animation)", key):
        return True, "UGC/avatar-specific path found outside the core directories."
    if re.search(r"(?:verification|rights-manager|intellectual-property|regional-pricing)", key):
        return True, "Publishing identity, rights, or pricing dependency."
    if key.startswith("reference/"):
        return False, "Engine API inclusion is resolved from narrative references and an explicit avatar API list."
    return False, "General game/Creator Store/cloud documentation outside the scoped avatar Marketplace workflow."


def topics(key: str) -> list[str]:
    result = []
    for tag, words in {
        "rigid": ("rigid", "accessories", "hair"), "layered": ("layered", "cage", "skinning"),
        "body": ("character", "body", "rigging", "avatar-setup"), "head": ("head", "facial", "facs"),
        "makeup": ("makeup", "eyelash", "eyebrow"), "classic": ("classic-clothing",),
        "animation": ("animation", "emote"), "publishing": ("marketplace", "monetiz", "verification", "rights"),
    }.items():
        if any(word in key.lower() for word in words):
            result.append(tag)
    return result or ["pipeline"]


def preserve_video_reviews(current: dict, prior: dict, retired: dict) -> tuple[dict, dict, dict]:
    """Keep analysis when links change; archived records are outside current coverage.

    Inputs and outputs are dictionaries keyed by video ID. Current source URLs and
    backlinks win; reviewed fields come from the last active or archived record.
    A restored record leaves the archive, so each video has one current disposition.
    """
    merged = copy.deepcopy(current)
    archived = copy.deepcopy(retired)
    generated_fields = {"id", "url", "backlinks", "linked_by_official_docs",
                        "current_link_status", "retired_at", "retirement_reason",
                        "retired_from_revision", "previously_linked_by_official_docs"}
    for video_id, video in merged.items():
        previous = prior.get(video_id, archived.get(video_id, {}))
        for field, value in previous.items():
            if field not in generated_fields:
                video[field] = copy.deepcopy(value)
        video["current_link_status"] = "current"
        archived.pop(video_id, None)
    removed = sorted(set(prior) - set(current))
    for video_id in removed:
        video = copy.deepcopy(prior[video_id])
        video.update(
            current_link_status="retired",
            linked_by_official_docs=False,
            previously_linked_by_official_docs=bool(video.get("linked_by_official_docs")),
            retired_at=datetime.now(timezone.utc).isoformat(),
            retirement_reason="No longer linked by the current scoped official source snapshot; retained analysis is historical, not current inventory coverage.",
        )
        if video.get("last_linked_revision"):
            video["retired_from_revision"] = video["last_linked_revision"]
        archived[video_id] = video
    return merged, archived, {"video_added": sorted(set(current) - set(prior)), "video_removed": removed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    out = SKILL / "corpus"
    (out / "documents").mkdir(parents=True, exist_ok=True)
    (out / "inventory").mkdir(exist_ok=True)
    revision = json.loads(fetch(f"{REPO}/commits/{args.revision}"))["sha"]
    tree = json.loads(fetch(f"{REPO}/git/trees/{revision}?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("Refusing a truncated source inventory.")
    now = datetime.now(timezone.utc).isoformat()
    llms = fetch(f"{DOCS}/docs/llms.txt")
    (out / "inventory/creator-hub-llms.txt").write_bytes(llms)
    paths = {entry["path"]: entry for entry in tree["tree"] if entry["type"] == "blob"}
    english = {p: e for p, e in paths.items() if p.startswith("content/en-us/") and p.endswith((".md", ".yaml"))}
    (out / "inventory/upstream-tree.json").write_text(json.dumps({"revision": revision, "truncated": False, "entries": list(english.values())}, indent=2) + "\n")
    records = {}
    previous = {}
    if (out / "sources.jsonl").exists():
        previous = {r["id"]: r for r in (json.loads(line) for line in (out / "sources.jsonl").read_text().splitlines())}
    for path, entry in english.items():
        rel = path.removeprefix("content/en-us/")
        key = key_for(rel)
        include, reason = classify(key)
        records[key] = {"id": key, "title": key.rsplit("/", 1)[-1], "source_path": path,
            "source_revision": revision, "upstream_blob_sha": entry["sha"], "canonical_url": f"{DOCS}/docs/{key}",
            "status": "included" if include else "excluded", "reason": reason,
            "inventories": ["github"], "topics": topics(key), "license": "CC-BY-4.0; code examples MIT"}
    for title, url in re.findall(r"\[([^\]]+)\]\((/docs/[^\s)]+\.md)\)", llms.decode()):
        key = key_for(url)
        include, reason = classify(key)
        if key not in records:
            records[key] = {"id": key, "title": title, "canonical_url": f"{DOCS}/docs/{key}",
                "source_path": None, "source_revision": None, "status": "included" if include else "excluded",
                "reason": reason, "inventories": [], "topics": topics(key), "license": "link and factual digest; live-only text not redistributed"}
        rec = records[key]
        rec["title"] = title
        rec["live_markdown_url"] = DOCS + url
        if "creator-hub" not in rec["inventories"]:
            rec["inventories"].append("creator-hub")
    texts = {}
    errors = []
    def retrieve(rec):
        try:
            if rec.get("source_path"):
                old = previous.get(rec["id"], {})
                cached = SKILL / old.get("local_path", "missing")
                if old.get("source_revision") == revision and cached.is_file():
                    data = cached.read_bytes()
                    if sha(data) == old.get("sha256"):
                        return rec["id"], data, None
                url = f"https://raw.githubusercontent.com/Roblox/creator-docs/{revision}/{rec['source_path']}"
            else:
                url = rec.get("live_markdown_url", f"{DOCS}/docs/en-us/{rec['id']}.md")
            data = fetch(url)
            text = data.decode()
            if text.lstrip().lower().startswith("<!doctype"):
                raise ValueError("HTML received for a documentation source")
            return rec["id"], data, None
        except Exception as exc:
            return rec["id"], None, str(exc)
    def consume(selected):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for key, data, error in pool.map(retrieve, selected):
                rec = records[key]
                rec["retrieved_at"] = now
                if error:
                    rec["fetch_status"] = "unavailable"
                    rec["fetch_error"] = error
                    errors.append({"id": key, "error": error})
                    continue
                text = data.decode()
                texts[key] = text
                rec["sha256"] = sha(data)
                rec["fetch_status"] = "retrieved"
                if rec.get("source_path"):
                    ext = Path(rec["source_path"]).suffix
                    destination = out / "documents" / (key + ext)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    rec["local_path"] = str(destination.relative_to(SKILL))
                    rec["analysis_status"] = "indexed; authored workflow references provide interpretation"
                else:
                    # Only store our own short factual digest for text without an established redistribution license.
                    headings = [line.lstrip("# ") for line in text.splitlines() if line.startswith("#")]
                    destination = out / "documents" / (key + ".json")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps({"url": rec["canonical_url"], "retrieved_at": now,
                        "remote_sha256": sha(data), "section_index": headings,
                        "notice": "Live-only source: fetch the linked original when needed; full text is not redistributed."}, indent=2) + "\n")
                    rec["local_path"] = str(destination.relative_to(SKILL))
                    rec["local_sha256"] = sha(destination.read_bytes())
                    rec["analysis_status"] = "section-indexed; consult live source"
    consume([r for r in records.values() if r["status"] == "included"])
    classes = set(API_CLASSES)
    enums = {"AccessoryType", "AvatarAssetType", "AssetType", "AvatarPromptResult", "BodyPart", "HumanoidRigType", "AvatarItemType", "AvatarItemType"}
    datatypes = {"CatalogSearchParams"}
    for text in texts.values():
        classes.update(re.findall(r"Class\.([A-Za-z][A-Za-z0-9_]*)", text))
        enums.update(re.findall(r"Enum\.([A-Za-z][A-Za-z0-9_]*)", text))
        datatypes.update(re.findall(r"Datatype\.([A-Za-z][A-Za-z0-9_]*)", text))
    defects = []
    apis = []
    for kind, names in (("classes", classes), ("enums", enums), ("datatypes", datatypes)):
        for name in sorted(names):
            key = f"reference/engine/{kind}/{name}"
            if key not in records:
                defects.append({"id": key, "reason": "Referenced identifier absent from upstream tree; not invented as an API."})
                continue
            rec = records[key]
            rec.update(status="included", reason="Referenced by scoped avatar documents or explicit avatar API dependency.", topics=["api"])
            if key not in texts:
                apis.append(rec)
    consume(apis)
    edges, videos, resources, external = [], {}, {}, {}
    # Inventory every outgoing documentation, API, resource and video dependency.
    for key, text in texts.items():
        for vid in re.findall(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})", text):
            item = videos.setdefault(vid, {"id": vid, "url": "https://www.youtube.com/watch?v=" + vid,
                "linked_by_official_docs": True, "channel_verified": False, "status": "indexed",
                "transcript_status": "not_reviewed", "visual_status": "not_reviewed",
                "reason": "Linked video; captions and visual settings require a separate review.", "backlinks": []})
            if key not in item["backlinks"]:
                item["backlinks"].append(key)
        for target in re.findall(r"(?:\]\(|(?:src|href)=[\"'])([^\s)\"']+)", text):
            if target.startswith(("#", "mailto:")):
                continue
            if target.startswith("http"):
                u = urllib.parse.urlparse(target)
                if u.netloc in ("create.roblox.com", "www.create.roblox.com") and u.path.startswith("/docs/"):
                    targetkey = key_for(u.path)
                else:
                    category = "resource" if re.search(r"\.(fbx|blend|zip|png|jpg|webp|gltf|glb|mp4|webm)(?:[?#]|$)", target, re.I) else "external"
                    registry = resources if category == "resource" else external
                    item = registry.setdefault(target, {"url": target, "status": "linked", "reason": "Reference resource; download/review is separate from prose coverage.", "backlinks": []})
                    if key not in item["backlinks"]:
                        item["backlinks"].append(key)
                    continue
            elif target.startswith("/docs/"):
                targetkey = key_for(target)
            elif re.search(r"\.(md|yaml)(?:#|$)", target):
                base = records[key].get("source_path") or ("content/en-us/" + key + ".md")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), target.split("#")[0]))
                targetkey = key_for(resolved.removeprefix("content/en-us/"))
            else:
                if "assets/" in target:
                    relative = target[target.index("assets/"):].split("#")[0]
                    url = "https://prod.docsiteassets.roblox.com/" + relative
                    item = resources.setdefault(url, {"url": url, "status": "linked", "reason": "Official illustrated/video/template dependency; original remains at the linked URL.", "backlinks": []})
                    if key not in item["backlinks"]:
                        item["backlinks"].append(key)
                continue
            rec = records.get(targetkey)
            reason = rec["reason"] if rec else "Unresolved upstream link or index/container; retained as a source defect."
            disposition = rec["status"] if rec else "unresolved"
            if not rec and re.match(r"^[a-z]{2}-[a-z]{2}/", targetkey):
                disposition = "excluded"
                reason = "Non-English localization link; this corpus intentionally uses English sources."
            edges.append({"from": key, "to": targetkey, "status": disposition, "reason": reason})
    for filename, obj in (("sources.jsonl", list(records.values())), ("links.jsonl", edges)):
        (out / filename).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in sorted(obj, key=lambda r: r.get("id", r.get("from", "")))))
    changes = {"added": [], "removed": [], "changed": [], "review_topics": []}
    for key, rec in records.items():
        old = previous.get(key)
        if not old and rec["status"] == "included":
            changes["added"].append(key)
        elif old and (old.get("sha256"), old.get("status")) != (rec.get("sha256"), rec.get("status")):
            changes["changed"].append(key)
    changes["removed"] = sorted(set(previous) - set(records))
    affected = changes["added"] + changes["changed"]
    changes["review_topics"] = sorted({topic for key in affected for topic in records[key].get("topics", [])})
    changes["notice"] = "Review authored category references, assets/rules.json and template hashes for changed topics. Machine indexing does not establish that curated instructions are current."
    prior_videos = {}
    if (out / "videos.json").exists():
        prior_videos = {v["id"]: v for v in json.loads((out / "videos.json").read_text())}
        if (out / "coverage.json").exists():
            old_revision = json.loads((out / "coverage.json").read_text()).get("revision")
            for video in prior_videos.values():
                if old_revision:
                    video.setdefault("last_linked_revision", old_revision)
    retired_videos = {}
    if (out / "retired-videos.json").exists():
        retired_videos = {v["id"]: v for v in json.loads((out / "retired-videos.json").read_text())}
    videos, retired_videos, video_changes = preserve_video_reviews(videos, prior_videos, retired_videos)
    for video in videos.values():
        video["last_linked_revision"] = revision
    changes.update(video_changes)
    (out / "changes.json").write_text(json.dumps(changes, indent=2) + "\n")
    for filename, obj in (("videos.json", list(videos.values())), ("retired-videos.json", list(retired_videos.values())), ("resources.json", list(resources.values())), ("external-links.json", list(external.values()))):
        (out / filename).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    for name in ("LICENSE", "LICENSE-CODE"):
        dest = SKILL / "licenses" / ("ROBLOX-" + name)
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(fetch(f"https://raw.githubusercontent.com/Roblox/creator-docs/{revision}/{name}"))
    counts = {s: sum(r["status"] == s for r in records.values()) for s in ("included", "excluded")}
    coverage = {"scope": "English Roblox Marketplace avatar creation, validation, publishing and related APIs",
        "revision": revision, "retrieved_at": now, "inventory_sha256": sha(llms), "upstream_tree_truncated": False,
        "counts": counts, "included_retrieved": len(texts), "unprocessed_candidates": 0,
        "fetch_failures": errors, "unresolved_api_identifiers": defects,
        "unresolved_links": [e for e in edges if e["status"] == "unresolved"],
        "videos_indexed": len(videos), "videos_transcripts_reviewed": sum(v["transcript_status"] == "reviewed" for v in videos.values()), "videos_visuals_reviewed": sum(v["visual_status"] == "reviewed" for v in videos.values()),
        "videos_visuals_sampled": sum(v["visual_status"] == "sampled" for v in videos.values()),
        "videos_retired": len(retired_videos),
        "video_scope_counts": {s: sum(v.get("scope", "unclassified") == s for v in videos.values()) for s in sorted({v.get("scope", "unclassified") for v in videos.values()})},
        "video_transcript_status_counts": {s: sum(v["transcript_status"] == s for v in videos.values()) for s in sorted({v["transcript_status"] for v in videos.values()})},
        "resource_links": len(resources), "external_links": len(external),
        "inventory_discrepancies": [{"id": r["id"], "inventories": r["inventories"],
            "reason": "Live-only: section metadata links to current original; no full-text redistribution assumed." if not r.get("source_path")
            else "GitHub-only: pinned licensed source retained; Engine API uses its own index rather than narrative llms."}
            for r in records.values() if r["status"] == "included" and len(r["inventories"]) == 1],
        "claims": {"inventory_classified": True, "all_videos_reviewed": False,
            "all_internet_tutorials_reviewed": False, "moderation_or_marketplace_approval": False},
        "maintenance": "Source inventory is complete for this snapshot; authored workflows and machine rules require review after sync."}
    (out / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"revision": revision, **counts, "retrieved": len(texts), "errors": len(errors), "videos": len(videos), "unresolved_links": len(coverage['unresolved_links'])}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
