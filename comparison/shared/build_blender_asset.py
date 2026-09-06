"""Run inside Blender to build/export the original round-two City Hall study.

Creates a separate scene and preserves existing scenes. Uses only local original
geometry; no asset service or telemetry is required. Default asset is GLB Y-up.
"""
from collections import defaultdict
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Euler, Vector

SHARED = Path(__file__).resolve().parent
SCENE = json.loads((SHARED / "scene.json").read_text(encoding="utf-8"))


def cube_mesh():
    verts = [(x,y,z) for z in [-.5,.5] for y in [-.5,.5] for x in [-.5,.5]]
    return verts, [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]


def lathe_mesh(profile, segments=32):
    verts = [(r*math.cos(i*math.tau/segments),r*math.sin(i*math.tau/segments),z) for r,z in profile for i in range(segments)]
    faces = [(row*segments+i,row*segments+(i+1)%segments,(row+1)*segments+(i+1)%segments,(row+1)*segments+i) for row in range(len(profile)-1) for i in range(segments)]
    faces += [tuple(reversed(range(segments))), tuple((len(profile)-1)*segments+i for i in range(segments))]
    return verts, faces


def sphere_mesh(segments=20, rings=12):
    return lathe_mesh([(max(0.00001,math.sin(j*math.pi/rings)), -math.cos(j*math.pi/rings)) for j in range(rings+1)], segments)


def tube_mesh(points, radius):
    points=[Vector(point) for point in points]
    verts=[]; faces=[]; sides=6
    for i,point in enumerate(points):
        tangent=(points[min(i+1,len(points)-1)]-points[max(0,i-1)]).normalized()
        u=tangent.cross(Vector((0,0,1)))
        if u.length < .001: u=tangent.cross(Vector((0,1,0)))
        u.normalize(); v=tangent.cross(u).normalized()
        for j in range(sides):
            verts.append(point+radius*(u*math.cos(j*math.tau/sides)+v*math.sin(j*math.tau/sides)))
    for i in range(len(points)-1):
        for j in range(sides): faces.append((i*sides+j,i*sides+(j+1)%sides,(i+1)*sides+(j+1)%sides,(i+1)*sides+j))
    return verts,faces


def group_for(p):
    if p.get("group"): return p["group"]
    identity=p["id"]
    if identity.startswith("building-"): return identity
    if identity.startswith(("roof-","windows-")): return "building-"+identity.split("-")[1]
    if p.get("collidable"): return "city-hall"
    if identity.startswith("tree-"): return "plaza-trees"
    if identity.startswith(("road-","stripe-")): return "street-network"
    return identity


def build():
    scene=bpy.data.scenes.new("City Hall - Round Two")
    bpy.context.window.scene=scene
    groups=defaultdict(lambda:{"vertices":[],"faces":[],"smooth":[],"label":"", "type":"feature"})
    materials={}
    mesh_templates={"box":cube_mesh(),"sphere":sphere_mesh(),"cylinder":lathe_mesh([(1,-.5),(1,.5)],24)}
    for primitive in SCENE["primitives"]:
        kind=primitive["kind"]
        if kind in mesh_templates: vertices,faces=mesh_templates[kind]
        elif kind=="lathe": vertices,faces=lathe_mesh(primitive["profile"],64)
        elif kind=="tube": vertices,faces=tube_mesh(primitive["points"],primitive["radius"])
        elif kind=="pediment":
            w=primitive["width"]/2; d=primitive["depth"]/2; h=primitive["height"]
            vertices=[(-w,-d,0),(w,-d,0),(0,-d,h),(-w,d,0),(w,d,0),(0,d,h)]
            faces=[(0,1,2),(3,5,4),(0,3,4,1),(1,4,5,2),(2,5,3,0)]
        else: raise ValueError("Unsupported original shape "+kind)
        if kind=="box": scale=primitive["size"]
        elif kind=="sphere": scale=[primitive["radius"]*value for value in primitive.get("scale",[1,1,1])]
        elif kind=="cylinder": scale=[primitive["radius"],primitive["radius"],primitive["height"]]
        else: scale=[1,1,1]
        transform=Matrix.Translation(primitive["position"]) @ Euler([math.radians(v) for v in primitive.get("rotation",[0,0,0])]).to_matrix().to_4x4() @ Matrix.Diagonal((*scale,1))
        color=tuple(primitive["color"])
        material_key=(color,primitive.get("roughness",.78),primitive.get("metallic",0),primitive.get("emission",0))
        if material_key not in materials:
            mat=bpy.data.materials.new(f"Civic material {len(materials):02d}")
            mat.diffuse_color=(*color,1); mat.use_nodes=True
            shader=mat.node_tree.nodes.get("Principled BSDF")
            shader.inputs["Base Color"].default_value=(*color,1)
            shader.inputs["Roughness"].default_value=material_key[1]
            shader.inputs["Metallic"].default_value=material_key[2]
            if material_key[3]:
                shader.inputs["Emission Color"].default_value=(*color,1)
                shader.inputs["Emission Strength"].default_value=material_key[3]
            materials[material_key]=mat
        group_id=group_for(primitive)
        group=groups[(group_id,material_key)]
        offset=len(group["vertices"])
        group["vertices"].extend(transform @ Vector(v) for v in vertices)
        group["faces"].extend(tuple(offset+index for index in face) for face in faces)
        group["smooth"].extend([kind in ("sphere","lathe","tube")]*len(faces))
        group["label"]="City Hall" if group_id=="city-hall" else primitive["label"]
        group["type"]="building" if primitive.get("collidable") else "feature"
    parents={}
    for index,((group_id,material_key),data) in enumerate(groups.items()):
        if group_id not in parents:
            parent=bpy.data.objects.new(group_id,None)
            parent["id"]=group_id; parent["label"]=data["label"]; parent["type"]=data["type"]
            scene.collection.objects.link(parent); parents[group_id]=parent
        mesh=bpy.data.meshes.new(f"{group_id}-mesh-{index}")
        mesh.from_pydata(data["vertices"],[],data["faces"]); mesh.materials.append(materials[material_key]); mesh.update()
        for polygon,smooth in zip(mesh.polygons,data["smooth"]): polygon.use_smooth=smooth
        obj=bpy.data.objects.new(f"{group_id}-surface-{index}",mesh)
        obj.parent=parents[group_id]; obj["id"]=group_id; obj["label"]=data["label"]; obj["type"]=data["type"]
        scene.collection.objects.link(obj)
    # Raised facade lettering, authored as geometry so every importer sees it.
    curve=bpy.data.curves.new("City Hall inscription","FONT")
    curve.body="CITY HALL"; curve.align_x="CENTER"; curve.size=1.15; curve.extrude=.025
    lettering=bpy.data.objects.new("city-hall-inscription",curve)
    lettering.location=(0,-.76,20.12); lettering.rotation_euler=(math.pi/2,0,0)
    scene.collection.objects.link(lettering)
    curve.materials.append(next(mat for key,mat in materials.items() if key[0]==(.36,.28,.16)))
    depsgraph=bpy.context.evaluated_depsgraph_get()
    text_mesh=bpy.data.meshes.new_from_object(lettering.evaluated_get(depsgraph))
    mesh_lettering=bpy.data.objects.new("city-hall-lettering",text_mesh)
    mesh_lettering.matrix_world=lettering.matrix_world.copy()
    scene.collection.objects.link(mesh_lettering)
    bpy.data.objects.remove(lettering,do_unlink=True)
    lettering=mesh_lettering
    lettering["id"]="city-hall"; lettering["label"]="City Hall inscription"; lettering["type"]="building"
    lettering.parent=parents["city-hall"]
    # Keep the native Blender source pleasant to inspect; lights/camera do not export.
    world=bpy.data.worlds.new("Civic daylight"); scene.world=world; world.use_nodes=True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value=(.32,.43,.50,1)
    world.node_tree.nodes.get("Background").inputs["Strength"].default_value=.45
    light_data=bpy.data.lights.new("Civic sun","SUN"); light_data.energy=2.5; light_data.angle=math.radians(6)
    light=bpy.data.objects.new("Civic sun",light_data); light.rotation_euler=(.4,-.5,-.6); scene.collection.objects.link(light)
    camera_data=bpy.data.cameras.new("Civic camera"); camera=bpy.data.objects.new("Civic camera",camera_data)
    camera.location=(95,-190,165); camera.rotation_euler=(Vector((0,15,25))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.lens=42; scene.collection.objects.link(camera); scene.camera=camera
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=="VIEW_3D":
                area.spaces.active.region_3d.view_distance=200
                area.spaces.active.region_3d.view_location=(0,15,25)
                area.spaces.active.clip_end=3000
    scene["source_note"]=SCENE["source_note"]
    bpy.ops.wm.save_as_mainfile(filepath=str(SHARED/"civic-center.blend"),compress=True)
    result=bpy.ops.export_scene.gltf(filepath=str(SHARED/"civic-center.glb"),export_format='GLB',use_active_scene=True,export_extras=True,export_cameras=False,export_lights=False,export_yup=True,export_animations=False)
    if 'FINISHED' not in result: raise RuntimeError("GLB export did not finish")
    report={"source_primitives":len(SCENE["primitives"]),"mesh_objects":len(groups)+1,"material_count":len(materials),"glb_bytes":(SHARED/"civic-center.glb").stat().st_size,"blender_version":bpy.app.version_string,"scene":scene.name}
    (SHARED/"asset-manifest.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    build()
