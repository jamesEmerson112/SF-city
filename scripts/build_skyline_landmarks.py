"""Run in Blender: original, source-positioned San Francisco skyline landmarks.

Each landmark has an isolated editable scene. Existing scenes, selection and
the active scene are preserved; the shared manifest is updated by stable ID.
"""

from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]


class Shapes:
    def __init__(self, record, scene):
        spec = importlib.util.spec_from_file_location(
            "civic_original_shapes", ROOT / "comparison/shared/build_blender_asset.py"
        )
        self.templates = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.templates)
        self.record, self.scene = record, scene
        self.groups = defaultdict(lambda: {"vertices": [], "faces": [], "smooth": []})
        self.materials = {}

    def material(self, name, color, roughness=0.7, metallic=0.0):
        value = bpy.data.materials.new(self.record["label"] + " " + name)
        value.diffuse_color = (*color, 1)
        value.use_nodes = True
        shader = value.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (*color, 1)
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metallic
        self.materials[name] = value
        return name

    def mesh(self, vertices, faces, material, transform=None, smooth=False):
        transform = transform if transform is not None else Matrix.Identity(4)
        group = self.groups[material]
        offset = len(group["vertices"])
        group["vertices"].extend(transform @ Vector(vertex) for vertex in vertices)
        group["faces"].extend(tuple(offset + index for index in face) for face in faces)
        group["smooth"].extend([smooth] * len(faces))

    def box(self, position, size, material, angle=0.0):
        transform = (
            Matrix.Translation(position)
            @ Matrix.Rotation(angle, 4, "Z")
            @ Matrix.Diagonal((*size, 1))
        )
        self.mesh(*self.templates.cube_mesh(), material, transform)

    def lathe(self, profile, material, position=(0, 0, 0), segments=48):
        self.mesh(
            *self.templates.lathe_mesh(profile, segments),
            material,
            Matrix.Translation(position),
            True,
        )

    def beam(self, start, end, radius, material):
        self.mesh(
            *self.templates.tube_mesh([start, end], radius), material, smooth=True
        )

    def observed_base(self, height, wall_material, roof_material):
        record = self.record
        center = Vector(record["building"]["centroid"])
        vertices = [
            (point[0] - center.x, point[1] - center.y, height)
            for point in record["roof"]["roof_vertices"]
        ]
        triangles = record["roof"]["roof_triangles"]
        faces = []
        for start in range(0, len(triangles), 3):
            face = list(triangles[start : start + 3])
            a, b, c = (Vector(vertices[index]) for index in face)
            if (b - a).cross(c - a).z < 0:
                face.reverse()
            faces.append(face)
        self.mesh(vertices, faces, roof_material)
        for ring_index, source_ring in enumerate(record["building"]["rings"]):
            ring = [
                Vector((point[0] - center.x, point[1] - center.y, 0))
                for point in source_ring
            ]
            area = sum(a.x * b.y - b.x * a.y for a, b in zip(ring, ring[1:] + ring[:1]))
            if (area < 0) != (ring_index > 0):
                ring.reverse()
            for a, b in zip(ring, ring[1:] + ring[:1]):
                self.mesh(
                    [a, b, b + Vector((0, 0, height)), a + Vector((0, 0, height))],
                    [(0, 1, 2, 3)],
                    wall_material,
                )

    def finish(self):
        parent = bpy.data.objects.new(self.record["label"], None)
        parent["id"] = self.record["id"]
        parent["label"] = self.record["label"]
        parent["source_note"] = self.record["source_note"]
        self.scene.collection.objects.link(parent)
        all_vertices = []
        for name, group in self.groups.items():
            mesh = bpy.data.meshes.new(self.record["label"] + " " + name)
            mesh.from_pydata(group["vertices"], [], group["faces"])
            mesh.materials.append(self.materials[name])
            mesh.update()
            for polygon, smooth in zip(mesh.polygons, group["smooth"]):
                polygon.use_smooth = smooth
            obj = bpy.data.objects.new(mesh.name, mesh)
            obj.parent = parent
            obj["id"] = self.record["id"]
            obj["label"] = self.record["label"]
            obj["type"] = "building"
            self.scene.collection.objects.link(obj)
            all_vertices.extend(group["vertices"])
        minimum = [min(vertex[axis] for vertex in all_vertices) for axis in range(3)]
        maximum = [max(vertex[axis] for vertex in all_vertices) for axis in range(3)]
        if not all(math.isfinite(value) for value in minimum + maximum):
            raise ValueError("Landmark mesh contains nonfinite geometry")
        if abs(minimum[2]) > 0.05 or abs(maximum[2] - self.record["height_m"]) > 0.05:
            raise ValueError(
                f"Landmark height differs from its reference: {minimum}, {maximum}"
            )
        return {
            "mesh_count": len(self.groups),
            "vertex_count": len(all_vertices),
            "mesh_bounds": {"min": minimum, "max": maximum},
        }


def pyramid(shapes):
    record = shapes.record
    height = record["height_m"]
    width = record["model_parameters"]["base_width_m"]
    yaw = math.radians(record["model_parameters"]["yaw_degrees"])
    stone = shapes.material("white aggregate", (0.70, 0.70, 0.64))
    trim = shapes.material("pale structural ribs", (0.86, 0.85, 0.76))
    glass = shapes.material("recessed windows", (0.12, 0.20, 0.23), 0.25, 0.45)
    roof = shapes.material("roof and plaza", (0.36, 0.37, 0.34))
    shapes.observed_base(1.0, stone, roof)

    def half_width(z):
        return width * 0.5 * (height - z) / (height - 18.3)

    for side in range(4):
        transform = Matrix.Rotation(yaw + side * math.pi / 2, 4, "Z")
        base, top = 18.3, 178.0
        b, t = half_width(base), half_width(top)
        shapes.mesh(
            [(-t, -t, top), (t, -t, top), (0, 0, height)], [(0, 1, 2)], trim, transform
        )

        def panel(left, right, low, high, material):
            low_width, high_width = half_width(low), half_width(high)
            shapes.mesh(
                [
                    (left * low_width, -low_width, low),
                    (right * low_width, -low_width, low),
                    (right * high_width, -high_width, high),
                    (left * high_width, -high_width, high),
                ],
                [(0, 1, 2, 3)],
                material,
                transform,
            )

        # Adjacent stone/window faces share edges. A second facade beneath thin
        # window decals would lose depth precision at city-scale camera ranges.
        for floor in range(44):
            bottom = base + floor * (top - base) / 44
            ceiling = base + (floor + 1) * (top - base) / 44
            low, high = bottom + 0.45, ceiling - 0.45
            panel(-1, 1, bottom, low, stone)
            panel(-1, 1, high, ceiling, stone)
            count = max(3, int(2 * half_width(high) / 2.7))
            cursor = -1.0
            for column in range(count):
                left, right = (
                    -1 + (column + 0.16) * 2 / count,
                    -1 + (column + 0.84) * 2 / count,
                )
                panel(cursor, left, low, high, stone)
                panel(left, right, low, high, glass)
                cursor = right
            panel(cursor, 1, low, high, stone)
        for column in range(6):
            x = (-0.83 + column / 3) * b
            a = transform @ Vector((x, -b, 1.0))
            c = transform @ Vector((x * 0.9, -b, 18.3))
            shapes.beam(a, c, 0.8, trim)
            if column < 5:
                d = transform @ Vector((x + b / 3, -b, 18.3))
                shapes.beam(a, d, 0.5, trim)
    # The two upper service wings are recognizable but deliberately approximate.
    for sign in (-1, 1):
        transform = Matrix.Rotation(yaw, 4, "Z")
        point = transform @ Vector((0, sign * 12.5, 146.5))
        shapes.box(point, (7.0, 7.0, 91.0), stone, yaw)
        point = transform @ Vector((0, sign * 16.05, 147.0))
        shapes.box(point, (1.0, 0.12, 89.0), glass, yaw)


def coit(shapes):
    record = shapes.record
    height = record["height_m"]
    parameters = record["model_parameters"]
    radius = parameters["shaft_radius_m"]
    cx, cy = parameters["shaft_center_offset_m"]
    stone = shapes.material("warm concrete", (0.78, 0.76, 0.66))
    trim = shapes.material("flutes and coping", (0.86, 0.84, 0.73))
    roof = shapes.material("podium roof", (0.47, 0.47, 0.41))
    shadow = shapes.material("interior recesses", (0.11, 0.13, 0.12))
    shapes.observed_base(5.97, stone, roof)
    shapes.lathe(
        [
            (radius + 0.6, 5.97),
            (radius + 0.6, 7.3),
            (radius, 8.0),
            (radius - 0.229, 50.5),
            (radius + 0.1, 51.4),
            (radius + 0.1, 53.0),
        ],
        stone,
        (cx, cy, 0),
        96,
    )
    shapes.lathe([(4.8, 51.4), (4.8, 61.0)], shadow, (cx, cy, 0), 48)
    shapes.lathe(
        [
            (radius + 0.2, 61.0),
            (radius + 0.65, 61.6),
            (radius + 0.65, 62.6),
            (radius + 0.35, 63.2),
            (radius + 0.35, height),
        ],
        trim,
        (cx, cy, 0),
        96,
    )
    for index in range(12):
        angle = math.radians(parameters["yaw_degrees"]) + index * math.tau / 12
        radial = Vector((math.cos(angle), math.sin(angle), 0))
        tangent = Vector((-math.sin(angle), math.cos(angle), 0))
        base = Vector((cx, cy, 0))
        shapes.beam(
            base + radial * (radius - 0.12) + Vector((0, 0, 8)),
            base + radial * (radius - 0.34) + Vector((0, 0, 51.4)),
            0.35,
            trim,
        )
        for side in (-1, 1):
            center = (
                base + radial * 6.35 + tangent * (side * 1.2) + Vector((0, 0, 56.5))
            )
            shapes.box(center, (0.52, 0.95, 7.0), trim, angle + math.pi / 2)
        # Semicircular exterior arch, with real open space below it.
        vertices = []
        for depth in (-0.45, 0.45):
            for r in (0.95, 1.47):
                for step in range(17):
                    theta = step * math.pi / 16
                    vertices.append(
                        base
                        + radial * (6.35 + depth)
                        + tangent * (r * math.cos(theta))
                        + Vector((0, 0, 59.8 + r * math.sin(theta)))
                    )
        faces = []
        for step in range(16):
            faces += [
                (step, step + 1, 17 + step + 1, 17 + step),
                (34 + step, 51 + step, 51 + step + 1, 34 + step + 1),
                (step, 34 + step, 34 + step + 1, step + 1),
                (17 + step, 17 + step + 1, 51 + step + 1, 51 + step),
            ]
        shapes.mesh(vertices, faces, trim)


def sutro(shapes):
    record = shapes.record
    parameters = record["model_parameters"]
    top = parameters["main_structure_height_m"]
    waist = parameters["waist_height_m"]
    red = shapes.material("international orange red", (0.65, 0.085, 0.035), 0.72)
    white = shapes.material("aviation white", (0.83, 0.82, 0.72), 0.65)
    concrete = shapes.material("concrete foundations", (0.39, 0.40, 0.37))
    angle0 = math.radians(parameters["yaw_degrees"])

    def center(leg, z):
        fraction = (z - 3) / (waist - 3) if z <= waist else (z - waist) / (top - waist)
        start = (
            parameters["base_radius_m"] if z <= waist else parameters["waist_radius_m"]
        )
        end = parameters["waist_radius_m"] if z <= waist else parameters["top_radius_m"]
        radius = start + (end - start) * fraction
        angle = angle0 + leg * math.tau / 3
        return Vector((radius * math.cos(angle), radius * math.sin(angle), z))

    def color(z):
        return red if int(z / 28.5) % 2 == 0 else white

    levels = [3 + i * (top - 3) / 36 for i in range(37)]
    for leg in range(3):
        foundation = center(leg, 3)
        shapes.box((foundation.x, foundation.y, 1.5), (6.0, 6.0, 3.0), concrete)
        offsets = [
            Vector(
                (
                    1.45 * math.cos(angle0 + leg * math.tau / 3 + j * math.tau / 3),
                    1.45 * math.sin(angle0 + leg * math.tau / 3 + j * math.tau / 3),
                    0,
                )
            )
            for j in range(3)
        ]
        for low, high in zip(levels, levels[1:]):
            material = color((low + high) / 2)
            for side in range(3):
                a, b = (
                    center(leg, low) + offsets[side],
                    center(leg, high) + offsets[side],
                )
                c, d = (
                    center(leg, low) + offsets[(side + 1) % 3],
                    center(leg, high) + offsets[(side + 1) % 3],
                )
                shapes.beam(a, b, 0.43, material)
                shapes.beam(a, c, 0.22, material)
                shapes.beam(a, d, 0.18, material)
                shapes.beam(c, b, 0.18, material)
        for band in range(8):
            end_height = record["height_m"] - leg * 3.5
            low = top + (end_height - top) * band / 8
            high = top + (end_height - top) * (band + 1) / 8
            anchor = center(leg, top)
            shapes.lathe(
                [
                    (0.78 * (1 - band * 0.065), low),
                    (0.78 * (1 - (band + 1) * 0.065), high),
                ],
                red if band % 2 else white,
                (anchor.x, anchor.y, 0),
                16,
            )
    major = [3, 40, 77, 114, 150, 189, top]
    for index, z in enumerate(major[1:]):
        previous = major[index]
        for leg in range(3):
            a, b = center(leg, z), center((leg + 1) % 3, z)
            shapes.beam(a, b, 0.5, color(z))
            shapes.beam(
                a + Vector((0, 0, -1.2)), b + Vector((0, 0, -1.2)), 0.3, color(z)
            )
            shapes.beam(center(leg, previous), b, 0.25, color((z + previous) / 2))
            shapes.beam(
                center((leg + 1) % 3, previous), a, 0.25, color((z + previous) / 2)
            )


def add_preview(scene, record):
    height = record["height_m"]
    world = bpy.data.worlds.new(record["label"] + " preview daylight")
    world.use_nodes = True
    world.node_tree.nodes.get("Background").inputs["Color"].default_value = (
        0.24,
        0.32,
        0.40,
        1,
    )
    world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.65
    scene.world = world
    light_data = bpy.data.lights.new(record["label"] + " sun", "SUN")
    light_data.energy = 2.0
    light_data.angle = math.radians(5)
    light = bpy.data.objects.new(light_data.name, light_data)
    light.rotation_euler = (0.45, -0.55, -0.6)
    scene.collection.objects.link(light)
    camera_data = bpy.data.cameras.new(record["label"] + " preview")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    camera.location = (height * 1.15, -height * 1.8, height * 0.85)
    camera.rotation_euler = (
        (Vector((0, 0, height * 0.48)) - camera.location)
        .to_track_quat("-Z", "Y")
        .to_euler()
    )
    camera_data.lens = 52
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 700
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(ROOT / (".cache/" + record["key"] + "-landmark.png"))


def build(render=False):
    data = json.loads(
        (ROOT / "assets/source/skyline-geometry.json").read_text(encoding="utf-8")
    )
    previous = bpy.context.window.scene
    scenes, entries = [], []
    try:
        for record in data["landmarks"]:
            scene = bpy.data.scenes.new("SF Skyline - " + record["label"])
            scene["generator_id"] = "civic-skyline-v1"
            scene["source_note"] = record["source_note"]
            bpy.context.window.scene = scene
            shapes = Shapes(record, scene)
            {"transamerica-pyramid": pyramid, "coit-tower": coit, "sutro-tower": sutro}[
                record["key"]
            ](shapes)
            measurements = shapes.finish()
            add_preview(scene, record)
            output = ROOT / ("viewer/assets/" + record["key"] + "-geographic.glb")
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
                raise RuntimeError("Landmark GLB export failed")
            entry = {
                "schema_version": 1,
                "id": record["id"],
                "label": record["label"],
                "asset": "res://assets/" + output.name,
                "origin": data["origin"],
                "position": record["building"]["centroid"],
                "place_on_terrain": True,
                "height_m": record["height_m"],
                "footprint": record["building"]["footprint"],
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "bytes": output.stat().st_size,
                "source_geometry_sha256": record["sha256"],
                "source_note": record["source_note"],
                "height_reference": record["height_reference"],
                "building_reference": record["building_reference"],
                "replaces_building_ids": record["replaces_building_ids"],
                "source_file": "assets/source/sf-skyline-landmarks.blend",
                "blender_version": bpy.app.version_string,
                **measurements,
            }
            entries.append(entry)
            entry.update(
                {
                    key: record[key]
                    for key in (
                        "walk_position",
                        "walk_node_id",
                        "walk_target_distance_m",
                    )
                }
            )
            scenes.append(scene)
            if render:
                bpy.ops.render.render(write_still=True)
        bpy.data.libraries.write(
            str(ROOT / "assets/source/sf-skyline-landmarks.blend"),
            set(scenes),
            path_remap="RELATIVE",
            compress=True,
        )
        manifest_path = ROOT / "viewer/assets/landmarks.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {"landmarks": []}
        )
        replaced = {entry["id"] for entry in entries}
        combined = [
            entry for entry in manifest["landmarks"] if entry["id"] not in replaced
        ] + entries
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "landmarks": sorted(combined, key=lambda entry: entry["id"]),
                },
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                [
                    {
                        key: entry[key]
                        for key in (
                            "label",
                            "asset",
                            "bytes",
                            "mesh_count",
                            "vertex_count",
                            "mesh_bounds",
                        )
                    }
                    for entry in entries
                ]
            )
        )
        return entries
    finally:
        bpy.context.window.scene = previous


if __name__ == "__main__":
    build()
