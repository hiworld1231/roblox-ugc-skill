"""Isolated Blender worker. Invoked by asset.py, never saves the source project."""
import json
import sys
import traceback
from pathlib import Path

import bmesh
import bpy

SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT))
from asset import RULES, finding, report


def is_cage(name):
    return name.endswith(("_InnerCage", "_OuterCage"))


def load_asset(path):
    extension = path.suffix.lower()
    if extension == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    else:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        if extension == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True)
        elif extension in (".gltf", ".glb"):
            bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            raise ValueError("Unsupported Blender input")


def measure(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        info = {"name": obj.name, "vertices": len(mesh.vertices), "triangles": len(mesh.loop_triangles),
            "nonmanifold_edges": sum(not edge.is_manifold for edge in bm.edges),
            "degenerate_faces": sum(face.calc_area() <= 1e-12 for face in bm.faces),
            "uv_layers": len(mesh.uv_layers), "materials": len(mesh.materials),
            "dimensions_blender_units": list(obj.dimensions),
            "armature_modifier": any(mod.type == "ARMATURE" for mod in obj.modifiers)}
        bm.free()
        info["uv_outside_0_1"] = sum(any(c < -1e-6 or c > 1 + 1e-6 for c in loop.uv)
            for layer in mesh.uv_layers for loop in layer.data)
        return info
    finally:
        evaluated.to_mesh_clear()


def cage_signature(obj):
    mesh = obj.data
    return {"vertices": len(mesh.vertices), "polygons": [list(p.vertices) for p in mesh.polygons],
            "uv": [[round(float(v), 6) for v in loop.uv] for layer in mesh.uv_layers for loop in layer.data]}


def audit(config):
    kind = config["kind"]
    workflow = config["workflow"]
    rule = RULES[kind]
    source = rule["source"]
    checks = []
    all_objects = list(bpy.context.scene.objects)
    if config.get("objects"):
        missing = set(config["objects"]) - {o.name for o in all_objects}
        if missing:
            raise ValueError("Selected objects not found: " + ", ".join(sorted(missing)))
        objects = [o for o in all_objects if o.name in config["objects"]]
    else:
        objects = [o for o in all_objects if o.type in ("MESH", "ARMATURE", "EMPTY") and not o.hide_render]
    render = [o for o in objects if o.type == "MESH" and not is_cage(o.name) and not o.name.endswith("_Att")]
    cages = [o for o in objects if o.type == "MESH" and is_cage(o.name)]
    armatures = [o for o in objects if o.type == "ARMATURE"]
    metrics = [measure(o) for o in render]
    by_name = {m["name"].removesuffix("_Geo"): m for m in metrics}
    if kind not in ("emote", "animation-pack"):
        checks.append(finding("render-geometry-present", "PASS" if render else "FAIL", [o.name for o in render], source))
    setup_input = workflow == "avatar-setup" and kind in ("body", "head", "layered")
    if setup_input:
        checks.append(finding("workflow", "NOT_CHECKED", "Avatar Setup input: pre-rig/cage/FACS readiness is deferred to the Studio-generated output. Front -Z differs from traditional body +Z.", "https://create.roblox.com/docs/avatar-setup/auto-setup-requirements"))
    if "render_mesh_count" in rule:
        checks.append(finding("render-mesh-count", "PASS" if len(render) == rule["render_mesh_count"] else "FAIL", {"actual": len(render), "required": rule["render_mesh_count"]}, source))
    if "max_triangles" in rule and not setup_input:
        # A paired shoe is two separate accessories; audit each accessory independently.
        count = sum(m["triangles"] for m in metrics)
        checks.append(finding("render-triangles", "PASS" if count <= rule["max_triangles"] else "FAIL", {"actual": count, "max": rule["max_triangles"], "cages_excluded": True}, source))
    if kind == "body" and not setup_input:
        missing = set(rule["parts"]) - set(by_name)
        checks.append(finding("body-part-names", "FAIL" if missing else "PASS", {"missing": sorted(missing), "extra_render_meshes": sorted(set(by_name) - set(rule["parts"]))}, source))
        if not missing:
            for name, budget in rule["budgets"].items():
                count = sum(by_name[p]["triangles"] for p in budget["parts"])
                checks.append(finding("triangles-" + name, "PASS" if count <= budget["max"] else "FAIL", {"actual": count, "max": budget["max"]}, source))
        attachments = {o.name.removesuffix("_Att") for o in objects if o.name.endswith("_Att")}
        absent = {name.removesuffix("Attachment") for name in rule["attachments"]} - attachments
        checks.append(finding("body-attachment-names", "FAIL" if absent else "PASS", {"missing": sorted(absent), "positions_not_validated": True}, source))
        missing_cages = [p + "_OuterCage" for p in rule["parts"] if p + "_OuterCage" not in {o.name for o in cages}]
        checks.append(finding("body-outer-cages", "FAIL" if missing_cages else "PASS", {"missing": missing_cages}, source))
    for metric in metrics:
        name = metric["name"]
        checks.append(finding(name + ":nonempty-mesh", "PASS" if metric["triangles"] else "FAIL", metric["triangles"], source))
        checks.append(finding(name + ":degenerate-faces", "FAIL" if metric["degenerate_faces"] else "PASS", metric["degenerate_faces"], source))
        if kind in ("rigid", "body", "head"):
            checks.append(finding(name + ":watertight", "FAIL" if metric["nonmanifold_edges"] else "PASS", metric["nonmanifold_edges"], source))
        checks.append(finding(name + ":uv-present", "PASS" if metric["uv_layers"] else "WARN", metric["uv_layers"], "https://create.roblox.com/docs/art/modeling/texture-specifications"))
        if metric["uv_outside_0_1"]:
            checks.append(finding(name + ":uv-range", "WARN", "UVs outside 0..1: inspect the category's permitted mapping and texture fit.", "https://create.roblox.com/docs/art/modeling/texture-specifications"))
        if metric["materials"] != 1:
            checks.append(finding(name + ":material-slots", "WARN", {"actual": metric["materials"], "action": "Bake/consolidate the intended render material; verify Studio import."}, source))
    if kind == "rigid":
        skinned = [m["name"] for m in metrics if m["armature_modifier"]]
        checks.append(finding("rigid-no-skinning", "FAIL" if skinned else "PASS", skinned, source))
    if kind in ("body", "head", "emote", "animation-pack") and not setup_input:
        checks.append(finding("rig-present", "PASS" if armatures else "FAIL", [a.name for a in armatures], source))
    # Only deform-bone groups count as bone influences, not arbitrary artistic vertex groups.
    for obj in render:
        bones = {bone.name for mod in obj.modifiers if mod.type == "ARMATURE" and mod.object
                 for bone in mod.object.data.bones if bone.use_deform}
        if not bones:
            if kind == "layered":
                checks.append(finding(obj.name + ":skinning", "NOT_CHECKED", "No manual deform weights: validate Automatic Skinning Transfer in Studio, if that is the chosen workflow.", "https://create.roblox.com/docs/avatar/automatic-skinning-transfer"))
            elif kind in ("body", "head") and not setup_input:
                checks.append(finding(obj.name + ":skinning", "FAIL", "Traditional body/head render mesh is missing its deform rig binding.", source))
            continue
        groups = {g.index: g.name for g in obj.vertex_groups if g.name in bones}
        too_many = unweighted = root_weights = 0
        for vertex in obj.data.vertices:
            active = [g for g in vertex.groups if g.group in groups and g.weight > 1e-6]
            too_many += len(active) > 4
            unweighted += not active
            root_weights += any(groups[g.group] == "Root" for g in active)
        checks.append(finding(obj.name + ":bone-influences", "FAIL" if too_many or unweighted or root_weights else "PASS", {"over_four": too_many, "unweighted": unweighted, "root_weighted": root_weights}, "https://create.roblox.com/docs/art/modeling/skin-a-humanoid-model"))
    if kind == "layered" and not setup_input:
        inner = [o.name for o in cages if o.name.endswith("_InnerCage")]
        outer = [o.name for o in cages if o.name.endswith("_OuterCage")]
        checks.append(finding("inner-outer-cage-presence", "PASS" if len(inner) == 1 and len(outer) == 1 else "FAIL", {"inner": inner, "outer": outer}, source))
    if cages:
        baseline = config.get("cage_baseline")
        if baseline:
            names = {o.name: cage_signature(o) for o in cages}
            with bpy.data.libraries.load(baseline, link=False) as (available, loaded):
                loaded.objects = [name for name in available.objects if name in names]
            signatures = {o.name.removesuffix(".001"): cage_signature(o) for o in loaded.objects if o and o.type == "MESH"}
            for name, sig in names.items():
                expected = signatures.get(name)
                checks.append(finding(name + ":cage-topology-uv", "NOT_CHECKED" if expected is None else "PASS" if sig == expected else "FAIL", "Baseline absent" if expected is None else {"matches_official_baseline": sig == expected}, source))
        else:
            checks.append(finding("cage-topology-uv", "NOT_CHECKED", "Provide --cage-baseline with the matching pinned official template. Cage names alone cannot verify topology/UV correspondence.", source))
        checks.append(finding("cage-fit-and-intersections", "NOT_CHECKED", "Test actual fit, overlap, layer order, body shapes and animations in Studio.", source))
    if kind in ("body", "head") and not setup_input:
        declared = set()
        for obj in objects:
            declared.update(str(k) for k in obj.keys())
            declared.update(v for v in obj.values() if isinstance(v, str))
            if obj.type == "MESH" and obj.data.shape_keys:
                declared.update(block.name for block in obj.data.shape_keys.key_blocks)
        required = set(RULES["head"]["facs"])
        checks.append(finding("facs-pose-declarations", "FAIL" if required - declared else "PASS", {"missing": sorted(required - declared), "note": "Declarations do not prove working exported facial animation."}, RULES["head"]["source"]))
        checks.append(finding("facs-deformation-and-landmarks", "NOT_CHECKED", "Run Roblox head validation and visually inspect blink, jaw, happy/sad expressions and cage landmarks.", "https://create.roblox.com/docs/avatar/dynamic-heads/validate"))
    used_images = set()
    for obj in render:
        for slot in obj.material_slots:
            if slot.material and slot.material.use_nodes:
                used_images.update(node.image for node in slot.material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image)
    for image in used_images:
        dims = list(image.size)
        if not all(dims):
            checks.append(finding("texture:" + image.name, "FAIL", "Image has no loaded pixels", source))
        elif kind == "makeup":
            checks.append(finding("texture:" + image.name, "PASS" if max(dims) <= 1024 else "FAIL", dims, source))
        elif kind in ("rigid", "layered", "body", "head"):
            checks.append(finding("texture:" + image.name, "FAIL" if max(dims) > 2048 else "WARN", {"dimensions": dims, "action": "Verify per-map restrictions: general texture and category specifications differ; 2048 is not approval for every map."}, source))
    checks.append(finding("attachment-relative-bounds", "NOT_CHECKED", {"studs_per_unit": config.get("studs_per_unit"), "dimensions": {m['name']: m['dimensions_blender_units'] for m in metrics}, "action": "Select body scale and accessory type; measure in the attachment frame in Studio."}, source))
    if kind in ("emote", "animation-pack"):
        actions = [{"name": a.name, "frame_range": list(a.frame_range)} for a in bpy.data.actions]
        checks.append(finding("animation-actions", "PASS" if actions else "FAIL", actions, source))
        checks.append(finding("animation-motion-loop-and-publishing-marker", "NOT_CHECKED", "Check clip list, duration, looping, bounds, CurveAnimation conversion and Emote marker in Studio.", source))
    checks.append(finding("normal-map-convention", "NOT_CHECKED", "Verify OpenGL tangent-space normal export; pixels alone do not establish the convention.", "https://create.roblox.com/docs/art/modeling/texture-specifications"))
    result = report(kind, checks, workflow=workflow, metrics=metrics, selected_objects=[o.name for o in objects],
                    tool_versions={"blender": bpy.app.version_string}, source_unchanged=True)
    return result, objects


def export_copy(config, result, objects):
    output = Path(config["output"])
    if result["blocking_failures"]:
        result["exported"] = False
        result["export_error"] = "Resolve blocking preflight findings before export."
        return
    if output.exists() or output.resolve() == Path(config["input"]).resolve():
        raise ValueError("Export output would overwrite existing data")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    if output.suffix.lower() == ".fbx":
        animated = config["kind"] in ("body", "head", "emote", "animation-pack")
        bpy.ops.export_scene.fbx(filepath=str(output), use_selection=True, object_types={"MESH", "ARMATURE", "EMPTY"},
            apply_scale_options="FBX_SCALE_UNITS", path_mode="COPY", embed_textures=True,
            add_leaf_bones=False, use_custom_props=True, bake_anim=animated,
            bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=False, bake_anim_simplify_factor=0.0)
    else:
        bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", use_selection=True,
            export_extras=True, export_animations=True)
    result["exported"] = output.is_file() and output.stat().st_size > 0
    result["export_path"] = str(output)
    result["stage"] = "export-with-offline-preflight"
    result["export_notice"] = "Import using the matching Studio workflow and run official validation; exporting is not Marketplace approval."


def main():
    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    try:
        load_asset(Path(config["input"]))
        result, objects = audit(config)
        if config.get("output"):
            export_copy(config, result, objects)
    except Exception as exc:
        result = report(config["kind"], [finding("blender-operation", "FAIL", str(exc), RULES[config["kind"]]["source"])])
        result["traceback"] = traceback.format_exc()
    print("UGC_REPORT_JSON:" + json.dumps(result))


if __name__ == "__main__":
    main()
