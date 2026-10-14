# Independent skill forward test

## Request

Create an original simple low-poly compass brooch as a rigid Roblox Front accessory. Deliver an editable Blender file, FBX, a painted/baked texture and a useful preview, plus available validation evidence and remaining Studio steps.

## Isolation

Used the installed `$roblox-ugc` skill and its documented references, corpus and helper commands. Did not inspect parent implementation/reports outside that skill. All test scripts, reference downloads, generated assets, renders and reports are inside `/tmp/roblox-ugc-forward-test`. No repository file was changed, no plugin was installed, no Studio interaction occurred and nothing was published/paid.

## Result

**PASS for the locally available authoring, export and offline checks.** Actual outputs exist: original editable Blender model; single-mesh FBX; painted albedo with metalness/roughness maps; front, hero, DCC reference-fit and FBX roundtrip previews. Geometry/UV/material assertions and source integrity are independently verified. Actual Roblox/Studio stages remain NOT_CHECKED, as instructed.

No blocking skill/helper defect was demonstrated by this task. The skill correctly routed the rigid workflow, provided source-backed category requirements, directed use of the real Blender runtime, exported a separate file, exposed remaining validation gaps and refused overwrite. Texture checks return conservative WARN results and require explicit per-map source review; this is a disclosed limitation, not Marketplace approval. The corpus source makes clear that importing rigid attachment objects from DCC is unsupported, so the local guide marker was excluded and the remaining AFT step creates BodyFrontAttachment.

## Exact checks performed

1. Retrieved rigid specification/export/import, texture specification, Blender scale and Classic mannequin sources through `scripts/corpus.py`.
2. Created original geometry and textures with local scripts and Blender 5.2.2 LTS.
3. Ran `scripts/asset.py preflight CompassBrooch.blend --kind rigid --objects CompassBrooch --studs-per-unit 1`, writing `offline_preflight.json`.
4. Ran `scripts/asset.py export --input CompassBrooch.blend --kind rigid --objects CompassBrooch --studs-per-unit 1 --output exports/CompassBrooch.fbx`, writing `export_report.json`.
5. Ran the same helper preflight on the actual exported FBX, writing `fbx_preflight.json`.
6. Independently imported FBX and asserted one mesh, one connected component, 192 triangles, 98 vertices, watertight edges, no degenerate faces, positive signed volume, unit scale, preserved dimensions, one UV/material, no armature/weighted vertices/colors and UV coordinates in 0–1.
7. Inspected the `.blend` hero/front/reference-fit previews and independently rendered FBX preview. Confirmed correct visible compass artwork and maintained material appearance. Verified three embedded/packed FBX texture images and their Base Color/Metallic/Roughness connections.
8. Checked SHA-256 of the original `.blend` after helpers against the helper's initial input hash. Repeated export to an existing path returned exit 2 with an explicit refusal and preserved the FBX hash.
9. Checked PNG image mode and resolution: albedo RGB 512×512; other two maps grayscale L 128×128.

Evidence files are named in `DELIVERY.md`; reproduction sources and full command logs are included. Do not describe the DCC mannequin render as real Studio acceptance.
