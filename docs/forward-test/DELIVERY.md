# Original low-poly Compass Brooch

Original brass-and-teal compass brooch for a rigid Roblox **Front** accessory, designed against the official Classic mannequin. Geometry and dial artwork were created for this isolated forward test.

## Files

- `CompassBrooch.blend` — editable original source; one render mesh, packed textures, preview camera/lights. No reference mannequin geometry is included.
- `exports/CompassBrooch.fbx` — exported using the installed Roblox UGC skill helper.
- `textures/CompassBrooch_ALB.png` — original painted 512×512 RGB albedo.
- `textures/CompassBrooch_MTL.png` / `CompassBrooch_RGH.png` — 128×128 grayscale metalness and roughness.
- `previews/hero.png` and `front.png` — inspected Blender previews.
- `previews/classic_fit_DCC_only.png` — reference placement preview in Blender; **not** an actual Studio fitting test.
- `previews/fbx_roundtrip.png` — independently reimported FBX render, visually inspected.
- `paint_texture.py` and `create_compass.py` — reproducible artwork/model creation sources.

## Verified

Blender 5.2.2 LTS; one connected closed mesh, 98 vertices, 192 triangles, zero nonmanifold edges, zero degenerate faces, one UV set inside 0–1, one material, no vertex colors and no skinning. Source/FBX dimensions are **0.8256 × 0.0774 × 0.8256 Blender units**; the chosen convention claims one Blender unit per stud, requiring confirmation after Studio import.

The supplied helper preflight and export completed with no blocking failures. An independent FBX reimport preserved geometry, unit scale, UVs and the three texture connections. All creation/export previews were inspected. Hashes confirm the helpers did not alter the `.blend`; a second export refused to overwrite the existing FBX, which retained its hash.

Detailed evidence: `offline_preflight.json`, `export_report.json`, `fbx_preflight.json`, `roundtrip_validation.json`, `file_integrity_validation.json` and `creation_record.json`.

## Remaining Studio steps

1. In a temporary Studio place, import the FBX using the matching traditional rigid workflow. Choose **Scale Unit: Stud**, verify Default/Classic rig scaling and orientation, then measure the actual imported dimensions. North should remain upright and the dial should face away from the torso.
2. Open Avatar → Accessory Fitting Tool. Choose the imported MeshPart, **Accessory → Front**, and **Classic** body scale. Position the back of the brooch on the front surface of the UpperTorso, with no floating gap or torso clipping.
3. Generate the MeshPart Accessory. Let AFT create the proper **BodyFrontAttachment**; the Blender guide empty is only an editing aid and was not exported as a rigid attachment. Confirm a single Handle, the generated attachment and expected accessory configuration, with no extraneous scripts or parts.
4. Verify the imported ColorMap/MetalnessMap/RoughnessMap. If Studio did not map them, assign the three provided PNGs to SurfaceAppearance using the appropriate authorized import workflow. No normal map is supplied. Set the Handle's Material to Plastic, Transparency to 0 and VertexColor to 1,1,1 as required.
5. Inspect front/side/rear fitting and movement on the intended Classic bodies, and test other relevant body shapes before claiming compatibility. Check the attachment-relative Front bounds using AFT; raw Blender dimensions do not prove those bounds.
6. In Studio play mode, run the official `AvatarCreationService:ValidateUGCAccessoryAsync(player, accessory, Enum.AccessoryType.Front)` and retain success/failure and original error strings. Correct any Roblox findings and repeat the applicable visual tests.

**NOT_CHECKED:** actual Studio import, imported scale/orientation, attachment-relative size bounds, official Roblox technical validation, live avatar fit/animation, moderation and Marketplace publication. Nothing was published, uploaded or paid for, and no Studio place was modified.

## Sources

The installed skill's corpus snapshot points to Roblox creator-docs revision `784c5e217446c65958d5d84f5c5f1d127951a8d7`.

- https://create.roblox.com/docs/avatar/rigid-accessories/specifications
- https://create.roblox.com/docs/avatar/rigid-accessories/export
- https://create.roblox.com/docs/avatar/rigid-accessories/import
- https://create.roblox.com/docs/art/modeling/texture-specifications
- https://create.roblox.com/docs/art/blender
- https://create.roblox.com/docs/avatar/resources#mannequin-models

The official Classic mannequin is sizing reference only, with download provenance in `reference/provenance.json`; it is excluded from the source asset and export.
