"""Run in Blender: original City Hall exterior aligned to observed footprint.

Creates an isolated scene and writes only that scene's dependencies to its native
source file. Existing scenes and the user's active scene are preserved.
"""

from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "assets/source/city-hall-geometry.json"


def build():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    footprint = data["building"]
    center = Vector(footprint["centroid"])
    roof_height = footprint["height_m"]
    target_height = data["architectural_height_m"]
    original_path = ROOT / "comparison/shared/build_blender_asset.py"
    spec = importlib.util.spec_from_file_location(
        "original_civic_shapes", original_path
    )
    shapes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shapes)
    previous_scene = bpy.context.window.scene
    scene = bpy.data.scenes.new("SF City Hall - geographic landmark")
    scene["generator_id"] = "civic-cityhall-geographic-v1"
    scene["source_note"] = data["source_note"]
    bpy.context.window.scene = scene
    groups = defaultdict(lambda: {"vertices": [], "faces": [], "smooth": []})
    materials = {}

    def material(name, color, roughness=0.8, metallic=0.0):
        if name in materials:
            return name
        result = bpy.data.materials.new("SF City Hall " + name)
        result.diffuse_color = (*color, 1)
        result.use_nodes = True
        shader = result.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (*color, 1)
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metallic
        materials[name] = result
        return name

    stone = material("granite", (0.67, 0.64, 0.56))
    trim = material("carved stone", (0.78, 0.75, 0.65))
    roof = material("roof", (0.40, 0.43, 0.42))
    glass = material("window glass", (0.10, 0.18, 0.20), 0.2, 0.3)
    bronze = material("bronze", (0.26, 0.22, 0.13), 0.35, 0.65)

    def add_mesh(vertices, faces, mat, transform=Matrix.Identity(4), smooth=False):
        group = groups[mat]
        offset = len(group["vertices"])
        group["vertices"].extend(transform @ Vector(vertex) for vertex in vertices)
        group["faces"].extend(tuple(offset + index for index in face) for face in faces)
        group["smooth"].extend([smooth] * len(faces))

    def box(position, size, mat=trim, angle=0.0):
        transform = (
            Matrix.Translation(position)
            @ Matrix.Rotation(angle, 4, "Z")
            @ Matrix.Diagonal((*size, 1))
        )
        add_mesh(*shapes.cube_mesh(), mat, transform)

    def cylinder(position, radius, height, mat=trim):
        transform = Matrix.Translation(position) @ Matrix.Diagonal(
            (radius, radius, height, 1)
        )
        add_mesh(*shapes.lathe_mesh([(1, -0.5), (1, 0.5)], 24), mat, transform, True)

    try:
        # The main mass uses the actual observed plan. Decoration is inferred.
        roof_vertices = [
            (point[0] - center.x, point[1] - center.y, roof_height)
            for point in data["roof"]["roof_vertices"]
        ]
        triangles = data["roof"]["roof_triangles"]
        roof_faces = []
        for offset in range(0, len(triangles), 3):
            face = list(triangles[offset : offset + 3])
            a, b, c = [Vector(roof_vertices[index]) for index in face]
            if (b - a).cross(c - a).z < 0:
                face.reverse()
            roof_faces.append(face)
        add_mesh(roof_vertices, roof_faces, roof)
        for ring_index, original in enumerate(
            footprint.get("rings", [footprint["footprint"]])
        ):
            ring = [
                Vector((point[0] - center.x, point[1] - center.y, 0))
                for point in original
            ]
            if (ring[0] - ring[-1]).length < 0.001:
                ring.pop()
            area = sum(a.x * b.y - b.x * a.y for a, b in zip(ring, ring[1:] + ring[:1]))
            if (area < 0) != (ring_index > 0):
                ring.reverse()
            for a, b in zip(ring, ring[1:] + ring[:1]):
                add_mesh(
                    [
                        a,
                        b,
                        b + Vector((0, 0, roof_height)),
                        a + Vector((0, 0, roof_height)),
                    ],
                    [(0, 1, 2, 3)],
                    stone,
                )
                difference = b - a
                length = difference.length
                if length < 0.1:
                    continue
                along = difference.normalized()
                outward = Vector((along.y, -along.x, 0))
                angle = math.atan2(along.y, along.x)
                midpoint = (a + b) / 2
                for z in (0.8, 8.8, 17.0, roof_height):
                    box(
                        midpoint + Vector((0, 0, z)),
                        (length + 0.15, 0.65, 0.45),
                        trim,
                        angle,
                    )
                if length < 7:
                    continue
                count = max(1, int(length / 5.4))
                for index in range(count):
                    point = a + along * length * (index + 0.5) / count
                    for z in (4.8, 12.3, 21.0):
                        box(
                            point + outward * 0.12 + Vector((0, 0, z)),
                            (3.0, 0.30, 4.8),
                            trim,
                            angle,
                        )
                        box(
                            point + outward * 0.30 + Vector((0, 0, z)),
                            (2.3, 0.12, 4.1),
                            glass,
                            angle,
                        )
                        box(
                            point + outward * 0.42 + Vector((0, 0, z)),
                            (0.10, 0.12, 4.15),
                            bronze,
                            angle,
                        )
                        box(
                            point + outward * 0.42 + Vector((0, 0, z)),
                            (2.35, 0.12, 0.12),
                            bronze,
                            angle,
                        )

        # Eight original columns face the east entrance. Their detailing is not
        # asserted to match a measured architectural survey.
        front = Vector((math.cos(math.radians(9.5)), math.sin(math.radians(9.5)), 0))
        tangent = Vector((-front.y, front.x, 0))
        local_plan = [
            Vector((p[0] - center.x, p[1] - center.y, 0))
            for p in footprint["footprint"]
        ]
        front_distance = max(point.dot(front) for point in local_plan)
        for index in range(8):
            point = front * (front_distance + 0.45) + tangent * ((index - 3.5) * 4.5)
            cylinder(point + Vector((0, 0, 1.1)), 1.15, 0.55)
            cylinder(point + Vector((0, 0, 11.0)), 0.78, 19.2)
            cylinder(point + Vector((0, 0, 20.8)), 1.0, 0.5)
            box(point + Vector((0, 0, 21.4)), (2.5, 2.5, 0.7), trim, math.radians(9.5))
        portico_center = front * front_distance
        angle = math.atan2(tangent.y, tangent.x)
        box(portico_center + Vector((0, 0, 23.1)), (39, 4.5, 2.4), trim, angle)
        pediment = [
            (-20, -2.3, 0),
            (20, -2.3, 0),
            (0, -2.3, 6.2),
            (-20, 2.3, 0),
            (20, 2.3, 0),
            (0, 2.3, 6.2),
        ]
        add_mesh(
            pediment,
            [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)],
            trim,
            Matrix.Translation(portico_center + Vector((0, 0, 24.3)))
            @ Matrix.Rotation(angle, 4, "Z"),
        )
        for index in range(6):
            depth = (6 - index) * 0.70
            box(
                portico_center
                + front * depth / 2
                + Vector((0, 0, 0.10 + index * 0.18)),
                (37, depth, 0.2 + index * 0.36),
                trim,
                angle,
            )

        # Reuse the original procedural dome shapes, preserving their round plan.
        # The base starts at the measured median roof; the finial reaches the
        # documented architectural height. No nonuniform horizontal stretching.
        dome_prefixes = (
            "central-roof-plinth",
            "drum-",
            "lower-drum",
            "upper-drum",
            "dome-",
            "lantern",
            "finial",
        )
        vertical_scale = (target_height - roof_height) / (77.98 - 21.5)
        dome_transform = (
            Matrix.Translation((0, 0, roof_height))
            @ Matrix.Diagonal((1, 1, vertical_scale, 1))
            @ Matrix.Translation((0, -30, -21.5))
        )
        for primitive in shapes.SCENE["primitives"]:
            if not primitive["id"].startswith(dome_prefixes):
                continue
            kind = primitive["kind"]
            if kind == "box":
                vertices, faces = shapes.cube_mesh()
                scale = primitive["size"]
            elif kind == "cylinder":
                vertices, faces = shapes.lathe_mesh([(1, -0.5), (1, 0.5)], 32)
                scale = [primitive["radius"], primitive["radius"], primitive["height"]]
            elif kind == "sphere":
                vertices, faces = shapes.sphere_mesh(32, 20)
                scale = [
                    primitive["radius"] * value
                    for value in primitive.get("scale", [1, 1, 1])
                ]
            elif kind == "lathe":
                vertices, faces = shapes.lathe_mesh(primitive["profile"], 64)
                scale = [1, 1, 1]
            elif kind == "tube":
                vertices, faces = shapes.tube_mesh(
                    primitive["points"], primitive["radius"]
                )
                scale = [1, 1, 1]
            else:
                raise ValueError("Unsupported dome primitive " + kind)
            color = primitive["color"]
            name = "dome-" + "-".join(str(round(value, 3)) for value in color)
            mat = material(
                name,
                color,
                primitive.get("roughness", 0.7),
                primitive.get("metallic", 0),
            )
            transform = (
                dome_transform
                @ Matrix.Translation(primitive["position"])
                @ Euler(
                    [
                        math.radians(value)
                        for value in primitive.get("rotation", [0, 0, 0])
                    ]
                )
                .to_matrix()
                .to_4x4()
                @ Matrix.Diagonal((*scale, 1))
            )
            add_mesh(
                vertices,
                faces,
                mat,
                transform,
                kind in ("cylinder", "sphere", "lathe", "tube"),
            )

        parent = bpy.data.objects.new("SF City Hall", None)
        parent["id"] = footprint["id"]
        parent["label"] = "San Francisco City Hall"
        parent["type"] = "building"
        scene.collection.objects.link(parent)
        for name, group in groups.items():
            mesh = bpy.data.meshes.new("City Hall " + name)
            mesh.from_pydata(group["vertices"], [], group["faces"])
            mesh.materials.append(materials[name])
            mesh.update()
            for polygon, smooth in zip(mesh.polygons, group["smooth"]):
                polygon.use_smooth = smooth
            obj = bpy.data.objects.new("City Hall " + name, mesh)
            obj.parent = parent
            obj["id"] = footprint["id"]
            obj["label"] = "San Francisco City Hall"
            obj["type"] = "building"
            scene.collection.objects.link(obj)
        world = bpy.data.worlds.new("City Hall geographic daylight")
        world.use_nodes = True
        world.node_tree.nodes.get("Background").inputs["Color"].default_value = (
            0.34,
            0.46,
            0.57,
            1,
        )
        world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.5
        scene.world = world
        light_data = bpy.data.lights.new("City Hall geographic sun", "SUN")
        light_data.energy = 2.0
        light_data.angle = math.radians(8)
        light = bpy.data.objects.new("City Hall geographic sun", light_data)
        light.rotation_euler = (0.5, -0.5, -0.8)
        scene.collection.objects.link(light)
        camera_data = bpy.data.cameras.new("City Hall geographic camera")
        camera = bpy.data.objects.new("City Hall geographic camera", camera_data)
        camera.location = (175, -170, 145)
        camera.rotation_euler = (
            (Vector((0, 0, 30)) - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        camera_data.lens = 40
        scene.collection.objects.link(camera)
        scene.camera = camera
        scene.render.engine = "BLENDER_EEVEE"
        scene.render.resolution_x = 900
        scene.render.resolution_y = 900
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(ROOT / ".cache/city-hall-landmark.png")
        source = ROOT / "assets/source/city-hall-geographic.blend"
        output = ROOT / "viewer/assets/city-hall-geographic.glb"
        bpy.data.libraries.write(
            str(source), {scene}, path_remap="RELATIVE", compress=True
        )
        result = bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLB",
            use_active_scene=True,
            export_extras=True,
            export_cameras=False,
            export_lights=False,
            export_yup=True,
            export_animations=False,
        )
        if "FINISHED" not in result:
            raise RuntimeError("Geographic City Hall export failed")
        asset_manifest = {
            "schema_version": 1,
            "id": footprint["id"],
            "label": "San Francisco City Hall",
            "asset": "res://assets/city-hall-geographic.glb",
            "origin": data["origin"],
            "position": [center.x, center.y, 0],
            "walk_position": data["walk_position"],
            "walk_node_id": data["walk_node_id"],
            "walk_target_distance_m": data["walk_target_distance_m"],
            "place_on_terrain": True,
            "height_m": target_height,
            "footprint": footprint["footprint"],
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size,
            "source_geometry_sha256": data["sha256"],
            "source_note": data["source_note"],
            "height_reference": data["height_reference"],
            "mesh_count": len(groups),
            "building_reference": data["building_reference"],
            "source_file": "assets/source/city-hall-geographic.blend",
            "blender_version": bpy.app.version_string,
        }
        manifest_path = ROOT / "viewer/assets/landmarks.json"
        existing = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {"landmarks": []}
        )
        entries = [
            entry
            for entry in existing["landmarks"]
            if entry.get("id") != asset_manifest["id"]
        ]
        entries.append(asset_manifest)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "landmarks": sorted(entries, key=lambda entry: entry["id"]),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        bpy.ops.render.render(write_still=True)
        print(
            json.dumps(
                {
                    key: asset_manifest[key]
                    for key in ("id", "asset", "sha256", "bytes", "mesh_count")
                }
            )
        )
    finally:
        bpy.context.window.scene = previous_scene


if __name__ == "__main__":
    build()
