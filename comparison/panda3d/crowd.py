"""Hardware-instanced articulated people for the shared renderer workload.

Seven part meshes share one dynamic instance buffer. No per-person scene nodes
are created; identities and route samples remain ordinary Python records.
"""
from array import array
import math

from panda3d.core import (
    BitMask32, Geom, GeomNode, GeomVertexArrayData, GeomVertexArrayFormat,
    GeomVertexData, GeomVertexFormat, InternalName, Material, NodePath, OmniBoundingVolume,
    Shader, Vec3,
)
from simplepbr import _shaderutils


class ResidentHandle:
    def __init__(self, crowd, index):
        self.crowd, self.index = crowd, index

    def getPos(self):
        return Vec3(*self.crowd.positions[self.index])

    def clearColorScale(self):
        self.crowd.selected = None

    def setColorScale(self, *_color):
        self.crowd.selected = self.index


class InstancedCrowd:
    def __init__(self, app):
        self.app = app
        self.parts = app.scene["character"]["parts"]
        self.residents, self.positions, self.headings = [], [], []
        self.selected = None
        self.visible_count = self.animated_count = 0
        self.sample_animated_index = None
        self.root = app.render.attachNewNode("articulated-people")
        self.root.hide(BitMask32.bit(2))
        self.shadow_root = app.render.attachNewNode("articulated-person-shadows")
        self.shadow_root.hide(BitMask32.bit(0))
        self.nodes, self.vertex_data = [], []

        attributes = GeomVertexArrayFormat()
        attributes.setDivisor(1)
        attributes.addColumn(InternalName.make("instance_position"), 4, Geom.NTFloat32, Geom.COther)
        attributes.addColumn(InternalName.make("instance_meta"), 4, Geom.NTFloat32, Geom.COther)
        colors = GeomVertexArrayFormat()
        colors.setDivisor(1)
        colors.addColumn(InternalName.make("instance_color"), 4, Geom.NTFloat32, Geom.CColor)
        attributes = GeomVertexArrayFormat.registerFormat(attributes)
        colors = GeomVertexArrayFormat.registerFormat(colors)
        self.instance_format, self.color_format = attributes, colors
        self.instance_data = GeomVertexArrayData(attributes, Geom.UHDynamic)
        self.shader = self._make_shader(False)
        self.shadow_shader = self._make_shader(True)
        for part in self.parts:
            geometry = app.shapes[part["kind"]].node().getGeom(0).makeCopy()
            source = geometry.getVertexData()
            fmt = GeomVertexFormat(source.getFormat())
            fmt.addArray(attributes)
            fmt.addArray(colors)
            fmt = GeomVertexFormat.registerFormat(fmt)
            vertices = GeomVertexData(source.convertTo(fmt))
            vertices.setArray(1, self.instance_data)
            geometry.setVertexData(vertices)
            geom_node = GeomNode("person-" + part["id"])
            geom_node.addGeom(geometry)
            geom_node.setBounds(OmniBoundingVolume())
            geom_node.setFinal(True)
            visible = self.root.attachNewNode(geom_node)
            shadow = self.shadow_root.attachNewNode(geom_node.makeCopy())
            material = Material("matte-" + part["id"])
            material.setBaseColor((1, 1, 1, 1))
            material.setMetallic(0)
            material.setRoughness(.85)
            for node, shader in [(visible, self.shader), (shadow, self.shadow_shader)]:
                node.setShader(shader, 10)
                node.setMaterial(material)
                node.setCollideMask(BitMask32.allOff())
                size = part.get("size", [part.get("radius", 1)] * 3)
                node.setShaderInput("part_size", Vec3(*size))
                node.setShaderInput("part_center", Vec3(*part["center"]))
                node.setShaderInput("part_pivot", Vec3(*part.get("pivot", part["center"])))
                node.setShaderInput("part_swing", float(part.get("swing", 0)))
            self.nodes.append(visible)
            self.vertex_data.append(vertices)

    @staticmethod
    def _make_shader(shadow):
        # This adapter pins simplepbr 0.13.1. Reuse its PBR/shadow material shader,
        # adding instance/gait transforms before its standard lighting pipeline.
        defines = {"USE_330": True, "MAX_LIGHTS": 8, "ENABLE_SHADOWS": not shadow}
        vertex = _shaderutils._load_shader_str("simplepbr.vert", defines.copy())
        declarations = """
in vec4 instance_position;
in vec4 instance_meta;
in vec4 instance_color;
uniform vec3 part_size;
uniform vec3 part_center;
uniform vec3 part_pivot;
uniform float part_swing;
uniform float crowd_time;
"""
        vertex = vertex.replace("void main() {", declarations + "\nvoid main() {")
        transforms = """
    float angle = part_swing * sin(6.28318530718 * (1.6 * crowd_time + instance_meta.x)) * 0.55 * instance_meta.y;
    float c = cos(angle), s = sin(angle);
    mat3 gait = mat3(c,0,-s, 0,1,0, s,0,c);
    float h = instance_position.w;
    mat3 heading = mat3(cos(h),sin(h),0, -sin(h),cos(h),0, 0,0,1);
    vec3 local = part_pivot + gait * (part_center - part_pivot + p3d_Vertex.xyz * part_size);
    vec4 model_position = vec4(instance_position.xyz + heading * local, 1.0);
    vec3 model_normal = heading * gait * normalize(p3d_Normal / part_size);
    vec3 model_tangent = vec3(1, 0, 0);
"""
        old = "    vec4 model_position = p3d_Vertex;\n    vec3 model_normal = p3d_Normal;\n    vec3 model_tangent = p3d_Tangent.xyz;"
        if old not in vertex:
            raise RuntimeError("Pinned simplepbr vertex interface changed")
        vertex = vertex.replace(old, transforms)
        vertex = vertex.replace("v_color = p3d_Color;", "v_color = vec4(mix(instance_color.rgb, vec3(1.0, 0.76, 0.18), instance_meta.z * 0.45), 1.0);")
        fragment = _shaderutils._load_shader_str("shadow.frag" if shadow else "simplepbr.frag", defines.copy())
        return Shader.make(Shader.SL_GLSL, vertex, fragment)

    def set_population(self, residents):
        self.residents = residents
        self.positions = [[0, 0, 0] for _ in residents]
        self.headings = [0.0] * len(residents)
        self.selected = None
        self.root.setInstanceCount(len(residents))
        self.shadow_root.setInstanceCount(len(residents))
        for part, vertices in zip(self.parts, self.vertex_data):
            role = part["color_role"]
            key = {"clothes": "color", "clothing": "color", "skin": "skin_color", "trousers": "trouser_color", "trouser": "trouser_color", "bag": "bag_color", "backpack": "bag_color"}.get(role, role)
            values = array("f")
            for resident in residents:
                values.extend([*resident[key], 1])
            colors = GeomVertexArrayData(self.color_format, Geom.UHStatic)
            colors.modifyHandle().setData(values.tobytes())
            vertices.setArray(2, colors)
        return {person["id"]: (ResidentHandle(self, i), person) for i, person in enumerate(residents)}

    def update(self, seconds):
        camera = self.app.camera
        camera_position = camera.getPos(self.app.render)
        quaternion = camera.getQuat(self.app.render)
        right, forward, up = quaternion.getRight(), quaternion.getForward(), quaternion.getUp()
        tan_h = math.tan(math.radians(self.app.camLens.getHfov()) / 2)
        tan_v = math.tan(math.radians(self.app.camLens.getVfov()) / 2)
        near, far = self.app.camLens.getNear(), self.app.camLens.getFar()
        candidates = []
        self.visible_count = 0
        for i, resident in enumerate(self.residents):
            position, direction = self.app.route_position(resident, seconds)
            self.positions[i] = [position.x, position.y, position.z]
            self.headings[i] = math.atan2(direction.y, direction.x)
            delta = position + Vec3(0, 0, .9) - camera_position
            distance2 = delta.lengthSquared()
            if distance2 <= 80 * 80:
                candidates.append((distance2, i))
            depth = delta.dot(forward)
            if near <= depth <= far and abs(delta.dot(right)) <= depth * tan_h and abs(delta.dot(up)) <= depth * tan_v:
                self.visible_count += 1
        animated = {index for _, index in sorted(candidates)[:300]}
        self.animated_count = len(animated)
        self.sample_animated_index = min(animated) if animated else None
        values = array("f")
        for i, resident in enumerate(self.residents):
            values.extend([*self.positions[i], self.headings[i], resident["phase"], float(i in animated), float(i == self.selected), 0])
        self.instance_data.modifyHandle().setData(values.tobytes())
        self.root.setShaderInput("crowd_time", float(seconds))
        self.shadow_root.setShaderInput("crowd_time", float(seconds))

    def ray_pick(self, origin, direction, nearest):
        """Return closest stable identity using human-sized resident bounds."""
        selected = None
        for i, position in enumerate(self.positions):
            minimum = [position[0] - .32, position[1] - .32, position[2]]
            maximum = [position[0] + .32, position[1] + .32, position[2] + 1.85]
            low, high = 0.0, nearest
            for axis in range(3):
                if abs(direction[axis]) < 1e-9:
                    if not minimum[axis] <= origin[axis] <= maximum[axis]:
                        high = -1
                        break
                else:
                    a = (minimum[axis] - origin[axis]) / direction[axis]
                    b = (maximum[axis] - origin[axis]) / direction[axis]
                    low, high = max(low, min(a, b)), min(high, max(a, b))
                    if high < low:
                        break
            if 0 <= low <= high and low < nearest:
                nearest, selected = low, self.residents[i]["id"]
        return selected
