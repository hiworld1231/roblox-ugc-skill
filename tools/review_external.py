#!/usr/bin/env python3
"""Record reproducible external-source metadata without redistributing third-party text."""
import concurrent.futures
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins/roblox-ugc/skills/roblox-ugc"
COMMUNITY = [
    ("https://devforum.roblox.com/t/ugc-hat-tutorial-cartoony-top-hat/1078816", "rigid", "Modeling/UV technique; admission and Blender UI are old; current official publishing rules take precedence."),
    ("https://devforum.roblox.com/t/how-to-make-ugc-hair-in-blender-28-pt-2/612848", "rigid", "Hair curve/texture techniques; old Blender and admission context require current-spec review."),
    ("https://devforum.roblox.com/t/3d-art-a-visual-representation-of-the-3d-pipeline/2659618", "pipeline", "Sculpt/retopology/UV/baking workflow; general techniques, not Marketplace acceptance evidence."),
    ("https://devforum.roblox.com/t/how-to-properly-configure-and-import-ugc-bundles/3094203", "body", "Body assembly/import guidance; verify policy and face-accessory details against live specs."),
    ("https://devforum.roblox.com/t/guide-layered-clothing-in-roblox-without-cages-or-rig-blender-avatar-setup/3793130", "layered", "Avatar Setup can generate components; the finished Marketplace item still needs cages/rig data and validation."),
    ("https://devforum.roblox.com/t/marvelous-designer-layered-clothing-cages/4140561", "layered", "MD/CLO-to-Blender techniques; custom cage topology/UV and output need independent validation."),
    ("https://devforum.roblox.com/t/modeling-an-outer-cage-for-avatar-accessories/2734001", "layered", "Partial/risky discussion; do not accept cage deletion or inferred upload success as normative guidance."),
    ("https://vimeo.com/1030106632", "head", "Dynamic-head tutorial candidate; metadata does not prove its video was reviewed."),
    ("https://www.youtube.com/watch?v=apZsJqsKdw4", "head", "Dynamic-head tutorial candidate; confirm FACS and caging against current official specs."),
    ("https://www.nocapmocap.com/blog/how-to-publish-a-roblox-emote", "animation", "Publishing walkthrough; its Studio marker correction must be corroborated by official guidance/current UI."),
]


def main():
    records = json.loads((SKILL / "corpus/external-links.json").read_text())
    mapping = {r["url"].split("#")[0]: r for r in records}
    previous_file = SKILL / "corpus/external-review.json"
    previous = {r["url"].split("#")[0]: r for r in json.loads(previous_file.read_text())} if previous_file.exists() else {}
    for url, topic, note in COMMUNITY:
        mapping[url] = {"url": url, "topic": topic, "type": "community", "review_note": note, "backlinks": []}
    results = []
    def one(item):
        url, rec = item
        rec = dict(rec)
        relevant = any(x in url for x in ("en.help.roblox.com", "devforum.roblox.com", "github.com/Roblox")) or rec.get("type") == "community"
        outside = any(x in url for x in ("skybox", "audio-loops", "buttes", "How-to-Make-Friends", "sunsetting-sets", "roblox-china"))
        if not relevant or outside:
            rec.update(disposition="excluded", reason="External non-UGC/general-reference link; retained for inventory traceability.")
            return rec
        rec.update(disposition="included", retrieved_at=datetime.now(timezone.utc).isoformat(), license="External rights retained; full text not redistributed.")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 roblox-ugc-source-review"})
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read(2 * 1024 * 1024)
                rec["resolved_url"] = response.url
                rec["http_status"] = response.status
            text = data.decode(errors="replace")
            rec["sha256"] = hashlib.sha256(data).hexdigest()
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
            rec["title"] = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else None
            rec["headings"] = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", text, re.S | re.I)][:60]
            rec["status"] = "metadata_retrieved"
            rec["analysis_status"] = "metadata and source role reviewed; full tutorial technique verification is task-specific"
            old = previous.get(url, {})
            if old.get("sha256") == rec["sha256"] and old.get("analysis_status"):
                rec["analysis_status"] = old["analysis_status"]
            if any(x in text.lower() for x in ("verify you are human", "just a moment", "enable javascript and cookies", "verify that you're not a robot", "javascript is disabled")):
                rec["status"] = "access_challenge"
                rec["analysis_status"] = "unavailable behind access challenge; not represented as reviewed text"
        except Exception as exc:
            rec.update(status="unavailable", error=str(exc), analysis_status="not_reviewed")
        return rec
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, mapping.items()))
    (SKILL / "corpus/external-review.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"external_candidates": len(results), "included": sum(x["disposition"] == "included" for x in results), "retrieved": sum(x.get("status") == "metadata_retrieved" for x in results), "unavailable": sum(x.get("status") in ("unavailable", "access_challenge") for x in results)}))


if __name__ == "__main__":
    main()
