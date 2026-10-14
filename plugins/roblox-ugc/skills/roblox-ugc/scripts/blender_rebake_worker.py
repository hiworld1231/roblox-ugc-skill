"""Blender-only worker: isolated shader inspection, duplicate-only topology/UV editing and baking."""
import hashlib
import json
import math
import sys
import traceback
from array import array
from pathlib import Path

import bpy

BAKE = "https://docs.blender.org/manual/en/4.5/render/cycles/baking.html"
UV = "https://docs.blender.org/manual/en/4.5/modeling/meshes/editing/uv.html"
REMESH = "https://docs.blender.org/manual/en/4.5/modeling/modifiers/generate/remesh.html"
CHECKS = []


def check(name, status, evidence, source=BAKE):
    CHECKS.append({"check": name, "status": status, "evidence": evidence, "source": source})


def fail(name, evidence, source=BAKE):
    check(name, "FAIL", evidence, source)
    raise ValueError(evidence)


def mesh_object(name):
    obj = bpy.context.scene.objects.get(name)
    if obj is None or obj.type != "MESH" or not obj.data.polygons:
        fail("mesh:" + str(name), "A nonempty named mesh is required: " + str(name))
    if obj.name.endswith(("_InnerCage", "_OuterCage", "_Att")):
        fail("protected-mesh", "Roblox cage/attachment meshes must not be re-UVed, remeshed or used as render targets.")
    return obj


def active_uv(obj, name=None):
    layer = obj.data.uv_layers.get(name) if name else next((u for u in obj.data.uv_layers if u.active_render), obj.data.uv_layers.active)
    if layer is None:
        fail(obj.name + ":uv", "Mesh lacks the requested UV map: " + str(name), UV)
    obj.data.uv_layers.active = layer
    layer.active_render = True
    return layer


def principled(material):
    if not material or not material.use_nodes:
        fail("source-material", "Source material must use nodes; inspect and prepare it explicitly.")
    outputs = [n for n in material.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output and n.target in ("ALL", "CYCLES")]
    if len(outputs) != 1 or not outputs[0].inputs["Surface"].is_linked:
        fail("surface-output", "One active Cycles material surface output is required: " + material.name)
    shader = outputs[0].inputs["Surface"].links[0].from_node
    if shader.type != "BSDF_PRINCIPLED":
        fail("surface-shader", "Unsupported/ambiguous surface graph in " + material.name + ": " + shader.type + ". Resolve shader groups/mixes manually; do not guess albedo.")
    if outputs[0].inputs["Displacement"].is_linked:
        fail("source-displacement", "Apply/inspect material displacement explicitly before transfer; this helper does not flatten it.")
    return outputs[0], shader


def upstream(node, seen=None):
    seen = set() if seen is None else seen
    if node in seen:
        return seen
    seen.add(node)
    for socket in node.inputs:
        for link in socket.links:
            upstream(link.from_node, seen)
    return seen


def inspect_source(obj):
    layer = active_uv(obj)
    if not obj.data.materials or any(slot.material is None for slot in obj.material_slots):
        fail("source-material-slots", "Every source face must have a defined material.")
    materials = []
    for material in obj.data.materials:
        output, shader = principled(material)
        reachable = upstream(shader)
        images = []
        for node in reachable:
            if node.type == "GROUP":
                fail("source-node-group", "Nested source node group requires manual inspection: " + node.name)
            if node.type == "UVMAP" and node.uv_map and not obj.data.uv_layers.get(node.uv_map):
                fail("source-uv-node", "Named source UV does not exist: " + node.uv_map, UV)
            if node.type == "TEX_IMAGE":
                image = node.image
                if image is None or image.source not in ("FILE", "GENERATED"):
                    fail("source-image", "Missing image or unsupported sequence/UDIM/movie at node " + node.name)
                if image.source == "FILE" and not image.packed_file and not Path(bpy.path.abspath(image.filepath)).is_file():
                    fail("source-image-file", "Source image file is unavailable: " + image.filepath)
                # Packed/file images are lazy-loaded after open_mainfile; reading pixels requests decoding.
                count = len(image.pixels)
                if not count or min(image.size) <= 0:
                    fail("source-image-pixels", "Source image has no decoded pixels: " + image.name)
                pixels = array("f", [0.0]) * count
                image.pixels.foreach_get(pixels)
                images.append({"node": node.name, "image": image.name, "path": image.filepath,
                    "size": list(image.size), "color_space": image.colorspace_settings.name,
                    "packed": bool(image.packed_file), "decoded_pixel_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                    "vector_source": [{"node": link.from_node.name, "type": link.from_node.type} for link in node.inputs["Vector"].links]})
        sockets = {}
        for name in ("Base Color", "Alpha", "Roughness", "Metallic", "Normal"):
            socket = shader.inputs.get(name)
            sockets[name] = {"links": [{"node": l.from_node.name, "socket": l.from_socket.name} for l in socket.links],
                "default": list(socket.default_value) if socket.type in ("RGBA", "VECTOR") else float(socket.default_value)}
        materials.append({"material": material.name, "shader": shader.type, "reachable_nodes": sorted(n.type for n in reachable),
            "images": images, "sockets": sockets})
    check("source-shader-inspection", "PASS", {"object": obj.name, "active_render_uv": layer.name, "frame": bpy.context.scene.frame_current, "materials": materials})
    check("material-map-scope", "WARN", "Only requested Principled Base Color/Alpha/Roughness/Metallic/Normal are transferred. Lighting, AO, emission, coat, transmission and other effects are not implicitly flattened.")
    return materials


def select(objects, active):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def duplicate_target(source, config):
    target = source.copy()
    target.data = source.data.copy()
    target.name = source.name + "_Rebaked"
    bpy.context.collection.objects.link(target)
    method = config.get("remesh", "none")
    if method != "none":
        facs_properties = [str(key) for key in source.keys() if str(key).startswith("Frame") or "facs" in str(key).lower()]
        if source.data.shape_keys or source.vertex_groups or source.parent or source.constraints or source.animation_data or source.modifiers or facs_properties:
            fail("remesh-protected-data", "Automatic remesh/decimate refuses shape keys, vertex groups, parent, constraints, animation or existing modifiers. Author a separate low target and preserve/rebuild rig/FACS/cages explicitly.", REMESH)
        select([target], target)
        if method == "decimate":
            ratio = config.get("ratio")
            if ratio is None or not 0 < ratio <= 1:
                fail("decimate-ratio", "Choose an explicit ratio greater than 0 and at most 1.", REMESH)
            modifier = target.modifiers.new("UGC_Decimate", "DECIMATE")
            modifier.ratio = ratio
        else:
            size = config.get("voxel_size")
            if size is None or size <= 0:
                fail("voxel-size", "Choose an explicit positive voxel size in Blender units.", REMESH)
            modifier = target.modifiers.new("UGC_Voxel", "REMESH")
            modifier.mode = "VOXEL"
            modifier.voxel_size = size
            modifier.use_remove_disconnected = False
        before = len(target.data.polygons)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        if not target.data.polygons:
            fail("remesh-result", "Remeshing produced an empty mesh; use a different resolution or target.", REMESH)
        check("remesh", "WARN", {"method": method, "source_faces": before, "target_faces": len(target.data.polygons),
            "ratio": config.get("ratio"), "voxel_size": config.get("voxel_size"),
            "note": "Inspect silhouette/detail. Automatic decimation or voxel remesh does not create deformation-ready retopology."}, REMESH)
    return target


def configure_uv(target, config):
    if target.modifiers:
        fail("target-modifiers", "Target modifiers must be deliberately applied on a working copy before transfer; evaluated UV topology may differ.")
    if config.get("uv", "keep") == "smart":
        if target.data.shape_keys:
            fail("target-shape-keys", "Automatic UV preparation refuses shape-key targets; author/select their UV deliberately.", UV)
        layer = target.data.uv_layers.new(name="UGC_RebakeUV")
        target.data.uv_layers.active = layer
        layer.active_render = True
        select([target], target)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        smallest = min([config.get("size", 1024), *config.get("map_sizes", {}).values()])
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=min(0.1, (config.get("margin", 8) + 2) / smallest), margin_method="FRACTION")
        bpy.ops.object.mode_set(mode="OBJECT")
        # Operators can rebuild CustomData storage; reacquire its RNA layer after leaving Edit Mode.
        layer = target.data.uv_layers.active
        layer.name = "UGC_RebakeUV"
        layer.active_render = True
    else:
        layer = active_uv(target, config.get("target_uv"))
    if any(not math.isfinite(c) or c < 0 or c > 1 for value in layer.data for c in value.uv):
        fail("target-uv-range", "Target UV must be finite and inside 0..1 for this atlas transfer.", UV)
    target.data.calc_loop_triangles()
    triangles = []
    raster = {}
    collisions = degenerate = 0
    grid = min(config.get("size", 1024), 256)
    for index, tri in enumerate(target.data.loop_triangles):
        coords = [layer.data[i].uv.copy() for i in tri.loops]
        area = (coords[1] - coords[0]).cross(coords[2] - coords[0])
        if abs(area) < 1e-10:
            degenerate += 1
            continue
        triangles.append(coords)
        low = [max(0, math.floor(min(v[axis] for v in coords) * grid)) for axis in (0, 1)]
        high = [min(grid, math.ceil(max(v[axis] for v in coords) * grid)) for axis in (0, 1)]
        a, b, c = coords
        for y in range(low[1], high[1]):
            for x in range(low[0], high[0]):
                px, py = (x + 0.5) / grid, (y + 0.5) / grid
                w1 = ((px - a.x) * (c.y - a.y) - (py - a.y) * (c.x - a.x)) / area
                w2 = ((b.x - a.x) * (py - a.y) - (b.y - a.y) * (px - a.x)) / area
                if min(w1, w2, 1 - w1 - w2) > 1e-6:
                    key = (x, y)
                    if key in raster and raster[key] != index:
                        collisions += 1
                    raster[key] = index
    if degenerate or collisions:
        fail("target-uv-layout", f"Target UV has {degenerate} degenerate triangles and {collisions} sampled overlapping pixels. Author a non-overlapping atlas.", UV)
    check("target-uv-layout", "PASS", {"name": layer.name, "triangles": len(triangles), "overlap_probe_resolution": grid,
        "note": "Raster overlap probe is sampled, not an exact UV intersection proof."}, UV)
    return layer, triangles


def override_source(source, originals, channel):
    indices = [p.material_index for p in source.data.polygons]
    source.data.materials.clear()
    for original in originals:
        material = original.copy()
        material.name = "UGC_Temporary_" + channel
        source.data.materials.append(material)
        output, shader = principled(material)
        tree = material.node_tree
        if channel == "base-color":
            # COLOR diffuse must retain Base Color while metal/alpha do not suppress the color pass.
            for name, value in (("Metallic", 0), ("Alpha", 1), ("Transmission Weight", 0), ("Subsurface Weight", 0)):
                socket = shader.inputs.get(name)
                if socket:
                    for link in list(socket.links):
                        tree.links.remove(link)
                    socket.default_value = value
        elif channel != "normal":
            emission = tree.nodes.new("ShaderNodeEmission")
            emission.inputs["Strength"].default_value = 1
            if channel == "coverage":
                emission.inputs["Color"].default_value = (1, 1, 1, 1)
            else:
                socket = shader.inputs[{"alpha": "Alpha", "roughness": "Roughness", "metallic": "Metallic"}[channel]]
                if socket.is_linked:
                    tree.links.new(socket.links[0].from_socket, emission.inputs["Color"])
                else:
                    v = float(socket.default_value)
                    emission.inputs["Color"].default_value = (v, v, v, 1)
            tree.links.new(emission.outputs[0], output.inputs["Surface"])
    for polygon, index in zip(source.data.polygons, indices):
        polygon.material_index = index


def bake_image(source, target, material, originals, channel, config):
    override_source(source, originals, channel)
    sizes = config.get("map_sizes", {})
    base_size = sizes.get("base-color", config.get("size", 1024))
    size = base_size if channel in ("coverage", "alpha") else sizes.get(channel, config.get("size", 1024))
    image = bpy.data.images.new("UGC_" + channel, width=size, height=size, alpha=True)
    image.colorspace_settings.name = "sRGB" if channel == "base-color" else "Non-Color"
    image.generated_color = (0, 0, 0, 0)
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    material.node_tree.nodes.active = node
    for other in material.node_tree.nodes:
        other.select = other == node
    select([source, target], target)
    options = {"type": "DIFFUSE" if channel == "base-color" else "NORMAL" if channel == "normal" else "EMIT",
        "use_selected_to_active": True, "use_clear": True, "margin": config.get("margin", 8), "margin_type": "EXTEND",
        "max_ray_distance": config["ray_distance"], "cage_extrusion": config.get("cage_extrusion", 0.0),
        "use_cage": bool(config.get("cage") or config.get("cage_extrusion", 0) > 0), "normal_space": "TANGENT", "normal_r": "POS_X", "normal_g": "POS_Y", "normal_b": "POS_Z"}
    if channel == "base-color":
        options["pass_filter"] = {"COLOR"}
    if config.get("cage"):
        options["cage_object"] = config["cage"]
    bpy.ops.object.bake(**options)
    pixels = array("f", [0.0]) * len(image.pixels)
    image.pixels.foreach_get(pixels)
    if any(not math.isfinite(v) for v in pixels):
        fail(channel + ":pixels", "Baked image contains non-finite values.")
    return image, node, pixels


def sample(image, pixels, uv):
    width, height = image.size
    x, y = max(0, min(width - 1, int(uv.x * width))), max(0, min(height - 1, int(uv.y * height)))
    return list(pixels[4 * (y * width + x):4 * (y * width + x) + 4])


def transfer(config, source):
    target = mesh_object(config["target"]) if config.get("target") else duplicate_target(source, config)
    if source == target or source.data == target.data:
        fail("separate-source-target", "Source and target must have separate object and mesh data.")
    if target.data.shape_keys and config.get("remesh", "none") != "none":
        fail("target-facs", "Remesh must not discard shape keys/FACS.", REMESH)
    layer, triangles = configure_uv(target, config)
    if config.get("cage"):
        cage = mesh_object(config["cage"])
        if cage in (source, target) or len(cage.data.vertices) != len(target.data.vertices) or [tuple(p.vertices) for p in cage.data.polygons] != [tuple(p.vertices) for p in target.data.polygons]:
            fail("bake-cage-topology", "Custom bake cage requires exactly the target vertex count and ordered face topology.")
    if not 0 <= config.get("margin", 8) < config.get("size", 1024) / 4:
        fail("margin", "Use a nonnegative bake margin below one quarter of image width.")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    originals = list(source.data.materials)
    original_indices = [p.material_index for p in source.data.polygons]
    target.data.materials.clear()
    material = bpy.data.materials.new("UGC_Rebaked_Material")
    material.use_nodes = True
    target.data.materials.append(material)
    for polygon in target.data.polygons:
        polygon.material_index = 0
    baked = {}
    channels = ["coverage", *config.get("maps", ["base-color", "alpha"])]
    # Alpha must be checked even for a ColorMap-only request, before choosing opaque padding.
    if "alpha" not in channels:
        channels.append("alpha")
    for channel in channels:
        baked[channel] = bake_image(source, target, material, originals, channel, config)
    source.data.materials.clear()
    for original in originals:
        source.data.materials.append(original)
    for polygon, index in zip(source.data.polygons, original_indices):
        polygon.material_index = index
    coverage, _, coverage_pixels = baked["coverage"]
    missing = samples = 0
    for tri in triangles:
        for weights in ((1/3, 1/3, 1/3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)):
            uv = sum((p * w for p, w in zip(tri, weights)), tri[0] * 0)
            samples += 1
            missing += sample(coverage, coverage_pixels, uv)[0] < 0.9
    if not samples or missing:
        fail("projection-coverage", f"{missing} of {samples} interior triangle probes missed the source. Adjust projection/cage or target, not texture paint.")
    check("projection-coverage", "PASS", {"triangle_interior_samples": samples, "missing": missing, "source_projection_distance": config["ray_distance"],
        "cage": config.get("cage"), "cage_extrusion": config.get("cage_extrusion", 0), "note": "Finite probes do not prove every texel; inspect seams and thin parts."})
    alpha_pixels = baked["alpha"][2]
    covered_alpha = [alpha_pixels[i] for i in range(0, len(coverage_pixels), 4) if coverage_pixels[i] > .99]
    opaque = config.get("alpha_policy", "preserve") == "opaque"
    if opaque and (not covered_alpha or min(covered_alpha) < .999):
        fail("opaque-source-alpha", "Opaque output was requested but source has actual transparency; preserve alpha or deliberately revise the source design. Transparency is never silently erased.")
    check("alpha-policy", "PASS", {"policy": config.get("alpha_policy", "preserve"), "source_covered_alpha_min": min(covered_alpha) if covered_alpha else None,
        "note": "Opaque fills only padding after verifying source opacity. Preserve retains projected alpha and transparent padding."})
    destination = Path(config["output"])
    destination.mkdir(parents=True, exist_ok=False)
    shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    outputs = {}
    for channel, (image, node, pixels) in baked.items():
        if channel == "base-color":
            for offset in range(0, len(pixels), 4):
                pixels[offset + 3] = 1 if opaque else max(0, min(1, alpha_pixels[offset])) if coverage_pixels[offset] > 0.5 else 0
        if opaque:
            for offset in range(3, len(pixels), 4):
                pixels[offset] = 1
        if channel == "base-color" or opaque:
            image.pixels.foreach_set(pixels)
            image.update()
        image.filepath_raw = str(destination / (channel + ".png"))
        image.file_format = "PNG"
        image.save()
        image.pack()
        outputs[channel] = {"path": str(destination / (channel + ".png")), "sha256": hashlib.sha256(Path(image.filepath_raw).read_bytes()).hexdigest(),
            "dimensions": list(image.size), "color_space": image.colorspace_settings.name,
            "rgb_min": min(pixels[0::4]), "rgb_max": max(pixels[0::4])}
        if channel in ("base-color", "roughness", "metallic"):
            material.node_tree.links.new(node.outputs["Color"], shader.inputs[{"base-color": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}[channel]])
        elif channel == "alpha" and not opaque and "base-color" not in baked:
            material.node_tree.links.new(node.outputs["Color"], shader.inputs["Alpha"])
        elif channel == "normal":
            normal = material.node_tree.nodes.new("ShaderNodeNormalMap")
            normal.uv_map = layer.name
            material.node_tree.links.new(node.outputs["Color"], normal.inputs["Color"])
            material.node_tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    if not opaque and "base-color" in baked:
        # Consume this image's Alpha output as well: Blender's color interpretation changes when
        # RGBA alpha is unused. A separate mask plus an unused embedded Alpha can darken RGB twice.
        material.node_tree.links.new(baked["base-color"][1].outputs["Alpha"], shader.inputs["Alpha"])
    source.hide_render = True
    source.hide_set(True)
    source["ugc_source_preserved"] = True
    target["ugc_texture_transfer"] = json.dumps({"source": source.name, "uv": layer.name, "maps": config.get("maps", ["base-color", "alpha"]), "ray_distance": config["ray_distance"]})
    select([target], target)
    # Pack originals as well so result.blend remains portable if external source textures move.
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(destination / "result.blend"), check_existing=True)
    check("bake-output", "PASS", {"target": target.name, "project": str(destination / "result.blend"), "images": outputs,
        "base_color_pass": "DIFFUSE COLOR, direct/indirect disabled", "data_pass": "explicit scalar socket -> EMIT, Non-Color", "normal_pass": "tangent +X +Y +Z"})
    check("appearance-comparison", "NOT_CHECKED", "Compare source and result on geometry with identical camera/light, including seams, thin parts, alpha, mipmaps and normal orientation. Coverage and nonempty pixels are not appearance proof.")
    check("roblox-acceptance", "NOT_CHECKED", "Run category preflight, Studio validation/fit and Roblox moderation separately. Re-UV/rebake does not guarantee resolution of a classifier false positive.", "https://create.roblox.com/docs/marketplace/validation-system")
    return {"target": target.name, "outputs": outputs, "project": str(destination / "result.blend")}


def main():
    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    details = {}
    try:
        bpy.ops.wm.open_mainfile(filepath=config["input"], load_ui=False, use_scripts=False)
        source = mesh_object(config["source"])
        active_uv(source, config.get("source_uv"))
        details["material_inspection"] = inspect_source(source)
        if config.get("mode", "rebake") == "rebake":
            details.update(transfer(config, source))
    except Exception as exc:
        if not any(c["status"] == "FAIL" for c in CHECKS):
            check("worker-error", "FAIL", str(exc))
        details["error"] = str(exc)
        details["traceback"] = traceback.format_exc(limit=3)
    failures = sum(c["status"] == "FAIL" for c in CHECKS)
    report = {"stage": "offline-texture-transfer", "checks": CHECKS, "blocking_failures": failures,
        "completed": failures == 0, "blender_version": bpy.app.version_string,
        "python_version": sys.version.split()[0], "marketplace_approved": False, **details}
    print("UGC_REBAKE_JSON:" + json.dumps(report))


if __name__ == "__main__":
    main()
