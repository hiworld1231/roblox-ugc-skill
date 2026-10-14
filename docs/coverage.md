# Corpus coverage — v0.2.0

Snapshot retrieved: 2026-10-14T07:30:32.363057+00:00. Roblox source revision: `784c5e217446c65958d5d84f5c5f1d127951a8d7`.

## Included

- 361 documentation/API sources; 1971 excluded candidates, each with a reason.
- All included sources retrieved; zero fetch failures and zero unclassified inventory candidates.
- 354 licensed full-text Markdown/API YAML sources; 7 live-only sources with linked section metadata.
- Complete official tutorial text: 7 rigid pages, 15 layered pages, 18 character-template pages and 4 facial-animation pages.
- 2337 image/template/media dependency links and 32 unique YouTube videos linked by included docs. Some videos are general authoring dependencies rather than Roblox-authored tutorials.

## What completeness means

The union of the complete English GitHub source inventory and live Creator Hub narrative index was classified. Relevant avatar/Marketplace/art pages, selected supporting workflows and referenced avatar APIs are included. General game, audio and Creator Store development are excluded. API expansion is deliberately bounded to avatar-related classes and narrative references, rather than recursively importing the entire Engine API.

Source paths, source revisions, hashes, inclusion/exclusion reasons and live-versus-GitHub differences are retained in [sources.jsonl](../plugins/roblox-ugc/skills/roblox-ugc/corpus/sources.jsonl) and [coverage.json](../plugins/roblox-ugc/skills/roblox-ugc/corpus/coverage.json). Documentation-link edges are in `corpus/links.jsonl`. Six upstream reference defects remain explicitly explained; they are not invented as APIs or hidden from the report.

## Open evidence gaps

**Videos:** 21 full available caption texts analyzed, one community head caption text analyzed separately, and 7 paused-frame visual samples. Zero full continuous visual walkthroughs. All 32 linked videos were visited and classified: 27 included, 2 supplemental, 3 excluded by scope. Six native caption exports remain unavailable, two contain only music/interjections, and one has unreliable speech recognition. The earlier sign-in blocker was resolved by the user. [Per-video analysis](video-analysis.md) preserves individual states and reasons; caption/visual findings are searchable locally.

**External sources:** Help Center, staff announcements and selected community tutorials have separate metadata/access/review records. Reviewed community text is summarized with current-spec caveats; inaccessible pages and videos remain marked. No claim covers every tutorial on the internet.

**Resources:** image/video/template links are inventoried; most binary resources are fetched on demand. Five supported project templates were downloaded and pinned by SHA-256. Their binaries and all third-party video content are not redistributed in the knowledge package.

**Application/game behavior:** CLI installation and local helpers were tested. RBX Toolbox source/operators, an isolated Blender MCP transport and re-UV/rebake helpers have separate evidence reports. Desktop UI loading, all category end-to-end authoring, actual Studio fitting/official validation of the example, moderation and Marketplace publication are separate and are not claimed.

## Maintenance

Use the skill's `scripts/corpus.py audit --json` for checksums/counts, `audit --live` for inventory drift and `sync --revision REF` for deliberate source refresh. Review changed documents, authored workflows and machine rules before releasing. Check the specific live fee/policy/eligibility page before current advice or a transaction; inventory equality alone is insufficient.

Licenses: [attribution](../plugins/roblox-ugc/skills/roblox-ugc/ATTRIBUTION.md). [Validation evidence](validation.json).
