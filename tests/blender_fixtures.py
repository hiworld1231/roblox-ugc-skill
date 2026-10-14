"""Generate assets with known geometric/rigging defects in an isolated directory."""
import json
import sys
from pathlib import Path

import bpy

dest = Path(sys.argv[sys.argv.index("--") + 1])
dest.mkdir(parents=True, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def cube(name="Asset"):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = name
    return obj


def save(name):
    bpy.ops.wm.save_as_mainfile(filepath=str(dest / (name + ".blend")))


reset()
cube()
save("valid-rigid")
cube("Extra")
save("multiple-meshes")
reset()
bpy.ops.mesh.primitive_plane_add()
save("open-rigid")
reset()
bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64)
save("over-budget")
reset()
obj = cube()
bpy.ops.object.armature_add()
arm = bpy.context.object
mod = obj.modifiers.new("skin", "ARMATURE")
mod.object = arm
save("skinned-rigid")
reset()
cube()
save("missing-layered-cages")
reset()
cube("Head_Geo")
save("missing-body-parts-and-facs")
reset()
obj = cube("Asset")
for name in ("Asset_InnerCage", "Asset_OuterCage"):
    cage = cube(name)
    uv = cage.data.uv_layers.new(name="UVMap") if not cage.data.uv_layers else cage.data.uv_layers[0]
save("cage-baseline")
for obj in bpy.context.scene.objects:
    if obj.type == "MESH" and obj.name.endswith("_OuterCage"):
        obj.data.uv_layers.active.data[0].uv.x += 0.25
save("changed-cage-uv")
reset()
bpy.ops.object.armature_add()
arm = bpy.context.object
arm.animation_data_create()
arm.animation_data.action = bpy.data.actions.new("OriginalEmote")
save("animation-rig-only")
reset()
obj = cube("Head_Geo")
bpy.ops.object.armature_add()
save("unbound-head")
print(json.dumps({"fixtures": str(dest)}))
