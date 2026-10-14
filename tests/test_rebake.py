"""Real Blender integration: different UVs must preserve known original surface colors."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/roblox-ugc/skills/roblox-ugc/scripts/rebake.py"
spec = importlib.util.spec_from_file_location("rebake", SCRIPT)
rebake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rebake)

FIXTURE = r'''
import bpy, sys
from pathlib import Path
dest = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
mesh = bpy.data.meshes.new('OriginalPatternMesh')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)], [], [(0,1,2,3)])
source = bpy.data.objects.new('Source', mesh)
bpy.context.collection.objects.link(source)
uv = mesh.uv_layers.new(name='OldUV')
for i, co in enumerate(((0,0),(1,0),(1,1),(0,1))):
    uv.data[i].uv = co
image = bpy.data.images.new('UnfamiliarFilename_notAnAlbedoGuess', width=128, height=128, alpha=True)
image.colorspace_settings.name = 'Non-Color'
pixels = []
for y in range(128):
    for x in range(128):
        u, v = (x+.5)/128, (y+.5)/128
        pixels.extend((.1+.7*u, .15+.6*v, .2 if (x//16+y//16)%2 else .8, .25+.6*u))
image.pixels[:] = pixels
image.pack()
material = bpy.data.materials.new('InspectedPrincipled')
material.use_nodes = True
shader = material.node_tree.nodes.get('Principled BSDF')
tex = material.node_tree.nodes.new('ShaderNodeTexImage')
tex.image = image
tex.interpolation = 'Linear'
material.node_tree.links.new(tex.outputs['Color'], shader.inputs['Base Color'])
material.node_tree.links.new(tex.outputs['Alpha'], shader.inputs['Alpha'])
shader.inputs['Roughness'].default_value=.37
shader.inputs['Metallic'].default_value=.61
source.data.materials.append(material)
target = source.copy()
target.data = source.data.copy()
target.name='Target'
bpy.context.collection.objects.link(target)
target.data.uv_layers.active.name='NewUV'
for i, co in enumerate(((.15,.85),(.15,.15),(.85,.15),(.85,.85))):
    target.data.uv_layers.active.data[i].uv=co
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'valid.blend'))
shader.inputs['Alpha'].default_value=1
for link in list(shader.inputs['Alpha'].links):
    material.node_tree.links.remove(link)
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'opaque.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
bpy.data.objects['Target'].data.uv_layers.active.data[2].uv=(.15,.85)
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'bad-target-uv.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
source=bpy.data.objects['Source']
for layer in list(source.data.uv_layers):
    source.data.uv_layers.remove(layer)
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'no-source-uv.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
bpy.data.objects['Target'].location.z=5
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'misses.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
tex = next(n for n in bpy.data.objects['Source'].data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE')
tex.image = None
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'missing-image.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
bpy.data.objects['Source'].vertex_groups.new(name='Head')
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'protected.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
material = bpy.data.objects['Source'].data.materials[0]
output = material.node_tree.nodes.get('Material Output')
emission = material.node_tree.nodes.new('ShaderNodeEmission')
material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'unknown-shader.blend'))
bpy.ops.wm.open_mainfile(filepath=str(dest/'valid.blend'))
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1)
ball=bpy.context.object
ball.name='StaticBall'
ball.data.materials.append(bpy.data.objects['Source'].data.materials[0])
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(island_margin=.04)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.wm.save_as_mainfile(filepath=str(dest/'static-remesh.blend'))
'''

SAMPLE = r'''
import bpy,json,sys
from pathlib import Path
dest=Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.open_mainfile(filepath=str(dest/'result.blend'),use_scripts=False)
mat=bpy.data.objects['Target'].data.materials[0]
images={n.image.name.removeprefix('UGC_'):n.image for n in mat.node_tree.nodes if n.type=='TEX_IMAGE'}
samples=[]
for u,v in ((.18,.22),(.37,.63),(.68,.34),(.83,.78),(.51,.43)):
    # Original world (u,v) -> rotated and inset target UV (0.15+0.7v,0.85-0.7u).
    uv=(.15+.7*v,.85-.7*u)
    values={}
    for channel,image in images.items():
        x=min(image.size[0]-1,int(uv[0]*image.size[0]));y=min(image.size[1]-1,int(uv[1]*image.size[1]))
        off=4*(y*image.size[0]+x)
        values[channel]=list(image.pixels[off:off+4])
    samples.append({'u':u,'v':v,'values':values})
print('SAMPLES_JSON:'+json.dumps(samples))
print('OPAQUE_JSON:'+json.dumps({name:{'dimensions':list(image.size),'alpha_min':min(image.pixels[3::4])} for name,image in images.items()}))
# Render appearance using the same emission+alpha extraction, independent of lighting noise.
scene=bpy.context.scene
scene.render.engine='CYCLES'; scene.cycles.samples=4;scene.cycles.device='CPU'
scene.render.resolution_x=256;scene.render.resolution_y=256;scene.render.resolution_percentage=100
scene.render.film_transparent=True
scene.view_settings.view_transform='Standard'
camera_data=bpy.data.cameras.new('ComparisonCamera')
camera=bpy.data.objects.new('ComparisonCamera',camera_data)
scene.collection.objects.link(camera)
camera.location=(0,0,3);camera.data.type='ORTHO';camera.data.ortho_scale=2.2
scene.camera=camera
renders=[]
for name,file in (('Source','before.png'),('Target','after.png')):
    for obj in (bpy.data.objects['Source'],bpy.data.objects['Target']):
        obj.hide_set(False);obj.hide_render=obj.name!=name
    obj=bpy.data.objects[name]
    material=obj.data.materials[0].copy();obj.data.materials[0]=material
    nodes=material.node_tree.nodes;links=material.node_tree.links
    shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
    output=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
    emission=nodes.new('ShaderNodeEmission');emission.inputs['Strength'].default_value=1
    base=shader.inputs['Base Color']
    links.new(base.links[0].from_socket,emission.inputs['Color'])
    transparent=nodes.new('ShaderNodeBsdfTransparent')
    mix=nodes.new('ShaderNodeMixShader')
    links.new(transparent.outputs[0],mix.inputs[1]);links.new(emission.outputs[0],mix.inputs[2])
    alpha=shader.inputs['Alpha']
    links.new(alpha.links[0].from_socket,mix.inputs[0])
    links.new(mix.outputs[0],output.inputs['Surface'])
    scene.render.filepath=str(dest/file)
    bpy.ops.render.render(write_still=True)
    # Load saved image because Render Result buffers can remain inaccessible in background mode.
    image=bpy.data.images.load(str(dest/file),check_existing=False)
    renders.append(list(image.pixels))
errors=[abs(a-b) for a,b in zip(*renders)]
print('COMPARISON_JSON:'+json.dumps({'channels':len(errors),'mean_absolute_error':sum(errors)/len(errors),'over_0_1':sum(e>.1 for e in errors)/len(errors),'scope':'base color and alpha on identical geometry/camera, stored Standard sRGB pixels'}))
'''


class LauncherTests(unittest.TestCase):
    def test_missing_input_fails(self):
        self.assertEqual(rebake.run({"input": "/no/such/file.blend", "source": "Source"})["blocking_failures"], 1)

    def test_unavailable_blender_is_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.blend"
            path.write_bytes(b"placeholder")
            report = rebake.run({"mode": "inspect", "input": str(path), "source": "Source"}, blender="/no/blender")
            self.assertFalse(report["completed"])


@unittest.skipUnless(shutil.which("blender"), "Blender not installed; integration tests explicitly skipped")
class RebakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ugc-rebake-test-")
        cls.dest = Path(cls.temp.name)
        fixture = cls.dest / "fixture.py"
        fixture.write_text(FIXTURE)
        subprocess.run([shutil.which("blender"), "--background", "--factory-startup", "--disable-autoexec", "--python", str(fixture), "--", str(cls.dest)], check=True, capture_output=True, timeout=90)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def transfer(self, name, **options):
        cfg = {"input": str(self.dest / (name + ".blend")), "source": "Source", "target": "Target", "output": str(self.dest / self._testMethodName),
            "ray_distance": .1, "size": 128, "margin": 3, "maps": ["base-color", "alpha", "roughness", "metallic", "normal"]}
        cfg.update(options)
        return rebake.run(cfg)

    def test_old_to_different_uv_preserves_surface_pattern_and_data(self):
        source = self.dest / "valid.blend"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        report = self.transfer("valid")
        self.assertTrue(report["completed"], report)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertTrue(report["source_file"]["unchanged"])
        output = Path(report["project"]).parent
        sampler = self.dest / "sample.py"
        sampler.write_text(SAMPLE)
        process = subprocess.run([shutil.which("blender"), "--background", "--factory-startup", "--disable-autoexec", "--python", str(sampler), "--", str(output)], check=True, capture_output=True, text=True, timeout=90)
        line = next(line for line in process.stdout.splitlines() if line.startswith("SAMPLES_JSON:"))
        samples = json.loads(line.removeprefix("SAMPLES_JSON:"))
        comparison=json.loads(next(line.removeprefix("COMPARISON_JSON:") for line in process.stdout.splitlines() if line.startswith("COMPARISON_JSON:")))
        self.assertLess(comparison["mean_absolute_error"],.015,comparison)
        self.assertLess(comparison["over_0_1"],.025,comparison)
        self.assertEqual(len(samples), 5)
        for sample in samples:
            u,v=sample["u"],sample["v"]
            # Stored sRGB PNG values must be decoded to compare to the original Non-Color shader data.
            color = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4 for v in sample["values"]["base-color"][:3]]
            self.assertAlmostEqual(color[0], .1 + .7*u, delta=.03)
            self.assertAlmostEqual(color[1], .15 + .6*v, delta=.03)
            expected_blue=.2 if (int(u*128)//16+int(v*128)//16)%2 else .8
            # Near a checker boundary the lower-resolution atlas can filter adjacent texels.
            if min((u*8)%1,1-(u*8)%1,(v*8)%1,1-(v*8)%1)>.15:
                self.assertAlmostEqual(color[2],expected_blue,delta=.035)
            self.assertAlmostEqual(sample["values"]["alpha"][0], .25+.6*u, delta=.03)
            self.assertAlmostEqual(sample["values"]["roughness"][0], .37, delta=.015)
            self.assertAlmostEqual(sample["values"]["metallic"][0], .61, delta=.015)
            normal = sample["values"]["normal"]
            self.assertAlmostEqual(normal[0], .5, delta=.02)
            self.assertAlmostEqual(normal[1], .5, delta=.02)
            self.assertAlmostEqual(normal[2], 1, delta=.02)
        self.assertTrue(any(c["check"]=="appearance-comparison" and c["status"]=="NOT_CHECKED" for c in report["checks"]))

    def test_missing_image_fails(self):
        report = self.transfer("missing-image")
        self.assertFalse(report["completed"])
        self.assertTrue(any(c["check"]=="source-image" and c["status"]=="FAIL" for c in report["checks"]),report)

    def test_opaque_output_refuses_true_source_transparency(self):
        report=self.transfer("valid",alpha_policy="opaque")
        self.assertFalse(report["completed"])
        self.assertTrue(any(c["check"]=="opaque-source-alpha" and c["status"]=="FAIL" for c in report["checks"]),report)

    def test_opaque_output_padding_and_per_map_dimensions(self):
        report=self.transfer("opaque",alpha_policy="opaque",map_sizes={"normal":32,"roughness":32,"metallic":32})
        self.assertTrue(report["completed"],report)
        self.assertEqual(report["outputs"]["base-color"]["dimensions"],[128,128])
        self.assertEqual(report["outputs"]["normal"]["dimensions"],[32,32])
        sampler=self.dest/"opaque-sample.py"
        sampler.write_text(SAMPLE.split("# Render appearance")[0])
        process=subprocess.run([shutil.which("blender"),"--background","--factory-startup","--disable-autoexec","--python",str(sampler),"--",str(Path(report["project"]).parent)],check=True,capture_output=True,text=True,timeout=90)
        values=json.loads(next(line.removeprefix("OPAQUE_JSON:") for line in process.stdout.splitlines() if line.startswith("OPAQUE_JSON:")))
        self.assertEqual(values["base-color"]["alpha_min"],1)
        self.assertEqual(values["normal"]["alpha_min"],1)

    def test_missing_source_uv_fails(self):
        self.assertFalse(self.transfer("no-source-uv")["completed"])

    def test_bad_target_uv_fails(self):
        self.assertFalse(self.transfer("bad-target-uv")["completed"])

    def test_projection_misses_fail(self):
        report=self.transfer("misses")
        self.assertFalse(report["completed"])
        self.assertTrue(any(c["check"]=="projection-coverage" and c["status"]=="FAIL" for c in report["checks"]),report)

    def test_unknown_shader_is_not_guessed(self):
        self.assertFalse(self.transfer("unknown-shader")["completed"])

    def test_remesh_preserves_rig_data_by_refusing(self):
        report=self.transfer("protected",target=None,uv="smart",remesh="decimate",ratio=.5)
        self.assertFalse(report["completed"])
        self.assertTrue(any(c["check"]=="remesh-protected-data" for c in report["checks"]),report)

    def test_duplicate_smart_uv_and_decimate_real_mesh(self):
        report=self.transfer("static-remesh",source="StaticBall",target=None,uv="smart",remesh="decimate",ratio=.5,ray_distance=.25,cage_extrusion=.15,maps=["base-color","alpha"])
        self.assertTrue(report["completed"],report)
        self.assertTrue(any(c["check"]=="remesh" and c["evidence"]["target_faces"]<c["evidence"]["source_faces"] for c in report["checks"]),report)

    def test_duplicate_voxel_remesh_real_mesh(self):
        report=self.transfer("static-remesh",source="StaticBall",target=None,uv="smart",remesh="voxel",voxel_size=.3,ray_distance=.5,cage_extrusion=.3,maps=["base-color","alpha"])
        self.assertTrue(report["completed"],report)
        self.assertTrue(any(c["check"]=="remesh" and c["evidence"]["method"]=="voxel" for c in report["checks"]),report)

    def test_output_collision_refused(self):
        report=self.transfer("valid",output=str(self.dest))
        self.assertEqual(report["checks"][0]["check"],"output")
        self.assertFalse(report["completed"])


if __name__ == "__main__":
    unittest.main()
