"""Panda3D viewer of the common City Hall renderer-comparison fixture.

Run with the workspace Python environment. No asset downloads are required.
The scene and resident routes are deliberately schematic; this is not live SF data.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import sys
import gltf
import simplepbr
from crowd import InstancedCrowd

from direct.gui.DirectGui import DirectFrame, DirectOptionMenu
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    BitMask32,
    ClockObject,
    CollisionBox,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionRay,
    CollisionSphere,
    CollisionTraverser,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    Point3,
    Point2,
    PNMImage,
    StringStream,
    TextNode,
    Vec3,
    loadPrcFileData,
)


FIXTURE = Path(__file__).resolve().parents[1] / "shared" / "scene.json"
sys.path.insert(0, str(FIXTURE.parent))
from detailed_scene import create_residents
PICK_MASK = BitMask32.bit(1)
SHADOW_MASK = BitMask32.bit(2)


def make_mesh(kind: str) -> NodePath:
    """Create unit primitives with explicit outward normals and CCW triangles."""
    vertices: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    indices: list[tuple[int, int, int]] = []

    def face(points, normals):
        offset = len(vertices)
        vertices.extend(zip(points, normals))
        for index in range(1, len(points) - 1):
            indices.append((offset, offset + index, offset + index + 1))

    if kind == "box":
        for normal, corners in [
            ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
            ((0, 0, -1), [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)]),
            ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
            ((0, 1, 0), [(1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)]),
            ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
            ((-1, 0, 0), [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)]),
        ]:
            face([tuple(value / 2 for value in p) for p in corners], [normal] * 4)
    elif kind == "cylinder":
        for i in range(32):
            a, b = i * math.tau / 32, (i + 1) * math.tau / 32
            x1, y1, x2, y2 = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
            n1, n2 = (x1, y1, 0), (x2, y2, 0)
            face([(x1, y1, -.5), (x2, y2, -.5), (x2, y2, .5), (x1, y1, .5)],
                 [n1, n2, n2, n1])
            face([(0, 0, .5), (x1, y1, .5), (x2, y2, .5)], [(0, 0, 1)] * 3)
            face([(0, 0, -.5), (x2, y2, -.5), (x1, y1, -.5)], [(0, 0, -1)] * 3)
    elif kind == "sphere":
        def point(latitude, longitude):
            return (math.cos(latitude) * math.cos(longitude),
                    math.cos(latitude) * math.sin(longitude), math.sin(latitude))

        for i in range(6):
            a, b = -math.pi / 2 + i * math.pi / 6, -math.pi / 2 + (i + 1) * math.pi / 6
            for j in range(12):
                c, d = j * math.tau / 12, (j + 1) * math.tau / 12
                points = [point(a, c), point(a, d), point(b, d), point(b, c)]
                face(points, points)
    else:
        raise ValueError(f"Unsupported primitive: {kind}")

    data = GeomVertexData(kind, GeomVertexFormat.getV3n3(), Geom.UHStatic)
    data.setNumRows(len(vertices))
    position = GeomVertexWriter(data, "vertex")
    normal = GeomVertexWriter(data, "normal")
    for p, n in vertices:
        position.addData3(*p)
        normal.addData3(*n)
    triangles = GeomTriangles(Geom.UHStatic)
    for a, b, c in indices:
        triangles.addVertices(a, b, c)
    triangles.closePrimitive()
    geometry = Geom(data)
    geometry.addPrimitive(triangles)
    node = GeomNode(kind)
    node.addGeom(geometry)
    result = NodePath(node)
    result.setCollideMask(BitMask32.allOff())
    return result


class CityHallDemo(ShowBase):
    def __init__(self, *, offscreen: bool = False, population: int | None = None):
        loadPrcFileData("city-hall", "\n".join([
            "window-title City Hall comparison | Panda3D", "win-size 1440 900",
            "audio-library-name null", "sync-video true", "framebuffer-multisample true",
            "multisamples 4", "notify-level warning",
        ]))
        super().__init__(windowType="offscreen" if offscreen else None)
        if not self.win:
            raise RuntimeError("Panda3D could not create a graphics window/buffer")
        self.disableMouse()
        self.scene = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.population = population or len(self.scene["residents"])
        self.render.setAntialias(AntialiasAttrib.MAuto)
        self.setBackgroundColor(.65, .77, .86)
        self._set_vertical_fov()
        self.camLens.setNearFar(.12, 2400)
        self.camNode.setCameraMask(BitMask32.bit(0))
        self.shapes = {kind: make_mesh(kind) for kind in ("box", "cylinder", "sphere")}
        self.object_nodes = {}
        self.resident_nodes = {}
        self.routes = {}
        self.selected = None
        self.selected_resident = self.scene["residents"][0]["id"] if self.scene["residents"] else None
        self.keys = {}
        self.dragging = False
        self.drag_distance = 0.0
        self.last_mouse = None
        self.frame_times = deque(maxlen=90)
        self.hud_elapsed = 0.0
        self._lighting()
        self.pipeline = simplepbr.init(msaa_samples=0 if offscreen else 4, use_330=True)
        self._scene_graph()
        self._picking()
        self._hud()
        self._controls()
        self.accept("aspectRatioChanged", self._set_vertical_fov)
        self.reset()
        # Initialize simplepbr's light/shadow state before deterministic smoke frames.
        for _ in range(3):
            self.taskMgr.step()
        self.taskMgr.add(self.update, "city-hall-update")

    def _set_vertical_fov(self):
        aspect = self.getAspectRatio()
        horizontal = math.degrees(2 * math.atan(math.tan(math.radians(55) / 2) * aspect))
        self.camLens.setFov(horizontal, 55)

    def _lighting(self):
        ambient = AmbientLight("sky")
        ambient.setColor((.10, .12, .15, 1))
        self.render.setLight(self.render.attachNewNode(ambient))
        sunlight = DirectionalLight("afternoon-sun")
        sunlight.setColor((2.7, 2.5, 2.1, 1))
        sunlight.setShadowCaster(True, 2048, 2048)
        sunlight.setCameraMask(SHADOW_MASK)
        sunlight.getLens().setFilmSize(520, 520)
        sunlight.getLens().setNearFar(1, 1000)
        sun = self.render.attachNewNode(sunlight)
        sun.setPos(-220, -270, 380)
        sun.lookAt(0, 0, 0)
        self.render.setLight(sun)

    def _primitive(self, item, parent):
        node = parent.attachNewNode(item.get("id", item["kind"]))
        node.setPos(*item["position"])
        geometry = self.shapes[item["kind"]].copyTo(node)
        kind = item["kind"]
        if kind == "box":
            geometry.setScale(*item["size"])
            if item["size"][2] < 1:
                # Thin pavement layers receive shadows but do not cast onto themselves.
                geometry.hide(SHADOW_MASK)
        elif kind == "cylinder":
            geometry.setScale(item["radius"], item["radius"], item["height"])
        else:
            geometry.setScale(*(item["radius"] * value for value in item.get("scale", [1, 1, 1])))
        geometry.setColor(*item["color"], 1)
        return node

    def _scene_graph(self):
        asset = FIXTURE.parent / self.scene["asset"]["file"]
        if not asset.is_file():
            raise FileNotFoundError(f"The Blender asset is required: {asset}")
        self.asset = NodePath(gltf.load_model(str(asset)))
        if self.asset.isEmpty():
            raise RuntimeError(f"glTF import produced an empty scene: {asset}")
        self.asset.reparentTo(self.render)
        self.asset_mesh_count = len(self.asset.findAllMatches("**/+GeomNode"))
        for mesh in self.asset.findAllMatches("**/+GeomNode"):
            identity = mesh.getNetTag("id") or mesh.getName()
            label = mesh.getNetTag("label") or identity
            kind = mesh.getNetTag("type") or "feature"
            mesh.setTag("selectable", identity)
            mesh.setCollideMask(PICK_MASK)
            owner = mesh
            parent = mesh.getParent()
            while not parent.isEmpty() and parent != self.asset and parent.getNetTag("id") == identity:
                owner, parent = parent, parent.getParent()
            self.object_nodes[identity] = (owner, {"id": identity, "label": label, "type": kind})
        self.asset_loaded = True
        for route in self.scene["routes"]:
            points = [Vec3(*point) for point in route["points"]]
            lengths = [(b - a).length() for a, b in zip(points, points[1:])]
            self.routes[route["id"]] = {**route, "vectors": points, "lengths": lengths,
                                          "total_length": sum(lengths)}
        self.crowd = InstancedCrowd(self)
        self.resident_nodes = self.crowd.set_population(create_residents(self.population))

    def set_population(self, count):
        count = int(count)
        if count not in self.scene["population_presets"]:
            raise ValueError("Population must be 200, 1000, or 5000")
        previous_selection = self.selected
        self.population = count
        self.resident_nodes = self.crowd.set_population(create_residents(count))
        self.select(previous_selection if previous_selection in self.resident_nodes or previous_selection in self.object_nodes else None)
        self.move_residents()
        self.update_camera(0)
        self.move_residents()
        self.update_hud()

    def change_population(self, direction):
        presets = self.scene["population_presets"]
        self.set_population(presets[(presets.index(self.population) + direction) % len(presets)])
        self.population_menu.set(presets.index(self.population), fCommand=0)

    def _picking(self):
        self.picker = CollisionTraverser("selection")
        self.pick_queue = CollisionHandlerQueue()
        self.pick_ray = CollisionRay()
        collider = CollisionNode("cursor-ray")
        collider.setFromCollideMask(PICK_MASK)
        collider.setIntoCollideMask(BitMask32.allOff())
        collider.addSolid(self.pick_ray)
        self.picker.addCollider(self.camera.attachNewNode(collider), self.pick_queue)

    def _hud(self):
        top = self.a2dTopLeft.attachNewNode("hud-top")
        DirectFrame(parent=top, frameColor=(.035, .07, .105, .94),
                    frameSize=(.025, .90, -.56, -.025))
        OnscreenText(parent=top, text="CITY HALL  /  PANDA3D", pos=(.07, -.1),
                     scale=.044, fg=(.52, .85, 1, 1), align=TextNode.ALeft, shadow=(0, 0, 0, .3))
        OnscreenText(parent=top, text="Civic Center renderer comparison", pos=(.07, -.158),
                     scale=.032, fg=(.83, .9, .95, 1), align=TextNode.ALeft)
        OnscreenText(parent=top, text="Blender architecture + articulated people\nSynthetic workload; not observed population",
                     pos=(.07, -.213), scale=.028, fg=(.7, .77, .83, 1), align=TextNode.ALeft)
        self.metrics = OnscreenText(parent=top, text="", pos=(.07, -.30), scale=.027,
                                   fg=(.91, .96, 1, 1), align=TextNode.ALeft, mayChange=True)
        self.population_menu = DirectOptionMenu(parent=top, items=[str(value) for value in self.scene["population_presets"]],
            initialitem=self.scene["population_presets"].index(self.population), scale=.043,
            pos=(.09, 0, -.505), command=self.set_population)
        OnscreenText(parent=top, text="people  |  +/- presets", pos=(.37, -.50), scale=.027,
                     fg=(.7, .82, .9, 1), align=TextNode.ALeft)
        bottom = self.a2dBottomLeft.attachNewNode("hud-bottom")
        DirectFrame(parent=bottom, frameColor=(.035, .07, .105, .94),
                    frameSize=(.025, 2.02, .025, .225))
        self.selection_text = OnscreenText(parent=bottom, text="", pos=(.07, .182), scale=.027,
                                          fg=(1, .81, .43, 1), align=TextNode.ALeft, mayChange=True)
        OnscreenText(parent=bottom, pos=(.07, .132), scale=.027, fg=(.9, .94, .98, 1),
                     align=TextNode.ALeft, text="1 Orbit   2 Walk   3 Follow   |   Space Pause   T 1x / 4x   R Reset")
        OnscreenText(parent=bottom, pos=(.07, .086), scale=.027, fg=(.75, .84, .91, 1),
                     align=TextNode.ALeft, text="Drag to look/orbit   Wheel to zoom   Click to inspect   |   Walk: WASD + arrow keys")
        OnscreenText(parent=bottom, pos=(.07, .043), scale=.027, fg=(.75, .84, .91, 1),
                     align=TextNode.ALeft, text="Walking stays within the district and stops at buildings.   Esc: release drag")

    def _controls(self):
        self.accept("1", self.set_mode, ["overhead"])
        self.accept("2", self.set_mode, ["walk"])
        self.accept("3", self.set_mode, ["follow"])
        self.accept("space", self.toggle_pause)
        self.accept("t", self.toggle_speed)
        self.accept("r", self.reset)
        self.accept("=", self.change_population, [1])
        self.accept("+", self.change_population, [1])
        self.accept("-", self.change_population, [-1])
        self.accept("escape", self.mouse_release, [False])
        self.accept("mouse1", self.mouse_press)
        self.accept("mouse1-up", self.mouse_release)
        self.accept("wheel_up", self.zoom, [.88])
        self.accept("wheel_down", self.zoom, [1.12])
        for key in ("w", "a", "s", "d", "shift", "arrow_left", "arrow_right", "arrow_up", "arrow_down"):
            self.keys[key] = False
            self.accept(key, self.keys.__setitem__, [key, True])
            self.accept(key + "-up", self.keys.__setitem__, [key, False])

    def reset(self):
        config = self.scene["camera"]
        self.simulation_time = 0.0
        self.paused = False
        self.speed = 1
        self.mode = "overhead"
        self.target = Vec3(*config["target"])
        self.distance = config["distance"]
        self.yaw = math.radians(config["yaw_degrees"])
        self.pitch = math.radians(config["pitch_degrees"])
        self.walk_position = Vec3(*config["walk_position"])
        towards = self.target - self.walk_position
        self.walk_yaw = math.atan2(towards.x, towards.y)
        self.walk_pitch = math.radians(config.get("walk_pitch_degrees", 0))
        self.dragging = False
        self.last_mouse = None
        self.selected_resident = self.scene["residents"][0]["id"] if self.scene["residents"] else None
        self.select(None)
        for key in self.keys:
            self.keys[key] = False
        self.move_residents()
        self.update_camera(0)
        self.update_hud()

    def set_mode(self, mode):
        if mode not in ("overhead", "walk", "follow"):
            raise ValueError(mode)
        if mode == "follow" and not self.resident_nodes:
            mode = "overhead"
        self.mode = mode
        # A farther near plane in overhead mode preserves pavement depth precision.
        self.camLens.setNear(1.0 if mode == "overhead" else .12)
        self.dragging = False
        self.last_mouse = None
        self.update_camera(0)
        self.move_residents()
        self.update_hud()

    def toggle_pause(self):
        self.paused = not self.paused
        self.update_hud()

    def toggle_speed(self):
        self.speed = 4 if self.speed == 1 else 1
        self.update_hud()

    def zoom(self, factor):
        self.distance = max(30, min(650, self.distance * factor))

    def mouse_press(self):
        if self.mouseWatcherNode and self.mouseWatcherNode.hasMouse():
            mouse = self.mouseWatcherNode.getMouse()
            self.last_mouse = (mouse.x, mouse.y)
            self.drag_distance = 0
            self.dragging = True

    def mouse_release(self, pick=True):
        if self.dragging and self.drag_distance < .012 and pick:
            self.pick()
        self.dragging = False
        self.last_mouse = None

    def pick(self):
        if not self.mouseWatcherNode or not self.mouseWatcherNode.hasMouse():
            return
        mouse = self.mouseWatcherNode.getMouse()
        self.pick_at(mouse.x, mouse.y)

    def pick_at(self, x, y):
        self.pick_ray.setFromLens(self.camNode, x, y)
        self.pick_queue.clearEntries()
        self.picker.traverse(self.render)
        self.pick_queue.sortEntries()
        selected, nearest = None, self.camLens.getFar()
        origin = self.camera.getPos(self.render)
        if self.pick_queue.getNumEntries():
            hit = self.pick_queue.getEntry(0)
            selected = hit.getIntoNodePath().getNetTag("selectable")
            nearest = (hit.getSurfacePoint(self.render) - origin).length()
        near_point, far_point = Point3(), Point3()
        self.camLens.extrude(Point2(x, y), near_point, far_point)
        direction = self.render.getRelativePoint(self.camera, far_point) - origin
        direction.normalize()
        resident = self.crowd.ray_pick(origin, direction, nearest)
        self.select(resident or selected)

    def select(self, identifier):
        all_nodes = self.object_nodes | self.resident_nodes
        if self.selected in all_nodes:
            all_nodes[self.selected][0].clearColorScale()
        self.selected = identifier
        self.selected_resident = identifier if identifier in self.resident_nodes else self.scene["residents"][0]["id"]
        if identifier in all_nodes:
            node, item = all_nodes[identifier]
            node.setColorScale(1.2, 1.14, .73, 1)
            if identifier in self.resident_nodes:
                self.selected_resident = identifier
                route = self.routes[item["route_id"]]["label"]
                text = f"{item['label']} | {item['home']} -> {item['destination']} | {route} | 3 Follow"
            else:
                text = f"Selected: {item['label']}"
        else:
            text = "Click a building or resident to inspect it."
        if hasattr(self, "selection_text"):
            self.selection_text.setText(text)

    def route_position(self, resident, seconds):
        route = self.routes[resident["route_id"]]
        remaining = ((seconds / route["duration"] + resident["phase"]) % 1) * route["total_length"]
        points = route["vectors"]
        for i, length in enumerate(route["lengths"]):
            if remaining <= length or i == len(route["lengths"]) - 1:
                direction = points[i + 1] - points[i]
                return points[i] + direction * (remaining / length if length else 0), direction
            remaining -= length
        return Vec3(points[0]), Vec3(0, 1, 0)

    def move_residents(self):
        self.crowd.update(self.simulation_time)
        self.render.setShaderInput("camera_world_position", self.camera.getPos(self.render))

    def eye_height(self, x, y):
        floor = float(self.scene["camera"]["walk_position"][2]) - 1.8
        for surface in self.scene.get("walk_surfaces", []):
            if surface["min"][0] <= x <= surface["max"][0] and surface["min"][1] <= y <= surface["max"][1]:
                progress = max(0, min(1, (y - surface["from_y"]) / (surface["to_y"] - surface["from_y"])))
                floor = max(floor, surface["from_z"] + progress * (surface["to_z"] - surface["from_z"]))
        return floor + 1.8

    def walk_allowed(self, x, y):
        radius = .7
        bounds = self.scene["bounds"]
        if not (bounds["min"][0] + radius <= x <= bounds["max"][0] - radius
                and bounds["min"][1] + radius <= y <= bounds["max"][1] - radius):
            return False
        return not any(box["min"][0] - radius <= x <= box["max"][0] + radius
                       and box["min"][1] - radius <= y <= box["max"][1] + radius
                       for box in self.scene["collision_boxes"])

    def update_camera(self, dt):
        self.camLens.setNear(1.0 if self.mode == "overhead" else .12)
        if self.dragging and self.mouseWatcherNode and self.mouseWatcherNode.hasMouse():
            mouse = self.mouseWatcherNode.getMouse()
            if self.last_mouse is not None:
                dx, dy = mouse.x - self.last_mouse[0], mouse.y - self.last_mouse[1]
                self.drag_distance += abs(dx) + abs(dy)
                if self.mode == "walk":
                    self.walk_yaw += dx * 2.0
                    self.walk_pitch = max(-1.35, min(1.35, self.walk_pitch + dy * 1.4))
                else:
                    self.yaw -= dx * 2.1
                    self.pitch = max(.12, min(1.48, self.pitch - dy * 1.5))
            self.last_mouse = (mouse.x, mouse.y)
        if self.mode == "walk":
            self.walk_yaw += (self.keys["arrow_right"] - self.keys["arrow_left"]) * dt * 1.5
            self.walk_pitch = max(-1.35, min(1.35, self.walk_pitch
                                  + (self.keys["arrow_up"] - self.keys["arrow_down"]) * dt))
            forward = Vec3(math.sin(self.walk_yaw), math.cos(self.walk_yaw), 0)
            right = Vec3(forward.y, -forward.x, 0)
            movement = forward * (self.keys["w"] - self.keys["s"]) + right * (self.keys["d"] - self.keys["a"])
            if movement.lengthSquared():
                movement.normalize()
                movement *= min(dt, .05) * (22 if self.keys["shift"] else 9)
                x, y = self.walk_position.x, self.walk_position.y
                if self.walk_allowed(x + movement.x, y):
                    self.walk_position.x += movement.x
                if self.walk_allowed(self.walk_position.x, y + movement.y):
                    self.walk_position.y += movement.y
            self.camera.setPos(self.walk_position)
            self.walk_position.z = self.eye_height(self.walk_position.x, self.walk_position.y)
            self.camera.setPos(self.walk_position)
            self.camera.lookAt(self.walk_position + forward * math.cos(self.walk_pitch)
                               + Vec3(0, 0, math.sin(self.walk_pitch)))
        else:
            target = self.target
            distance = self.distance
            if self.mode == "follow":
                node, resident = self.resident_nodes[self.selected_resident]
                _, direction = self.route_position(resident, self.simulation_time)
                direction.normalize()
                target = node.getPos() + Vec3(0, 0, 2)
                self.camera.setPos(node.getPos() - direction * 13 + Vec3(0, 0, 8))
                self.camera.lookAt(target)
                return
            self.camera.setPos(target + Vec3(math.cos(self.yaw) * math.cos(self.pitch),
                                            math.sin(self.yaw) * math.cos(self.pitch),
                                            math.sin(self.pitch)) * distance)
            self.camera.lookAt(target)

    def update_hud(self):
        ms = sum(self.frame_times) / len(self.frame_times) * 1000 if self.frame_times else 0
        timing = f"{1000 / ms:5.1f} FPS  /  {ms:5.1f} ms" if len(self.frame_times) >= 30 else "Timing starts during interactive playback"
        self.metrics.setText(f"{self.mode.upper()}  |  {'PAUSED' if self.paused else 'RUNNING'}  |  {self.speed}x\n"
                             f"Time {self.simulation_time:6.1f}s | {len(self.resident_nodes)} simulated\n"
                             f"{self.crowd.visible_count} in frustum | {self.crowd.animated_count} with gait\n"
                             f"{self.asset_mesh_count} GLB meshes | seven body-part batches\n{timing}")

    def advance(self, dt):
        if not self.paused:
            self.simulation_time += dt * self.speed
        self.move_residents()
        self.update_camera(dt)
        self.move_residents()

    def update(self, task):
        real_dt = ClockObject.getGlobalClock().getDt()
        self.frame_times.append(real_dt)
        self.advance(min(real_dt, .1))
        self.hud_elapsed += real_dt
        if self.hud_elapsed > .2:
            self.update_hud()
            self.hud_elapsed = 0
        return task.cont

    def get_state(self):
        sample = next(iter(self.resident_nodes.values()))[0].getPos() if self.resident_nodes else Vec3(0)
        animated = self.crowd.sample_animated_index
        gait = math.sin(math.tau * (1.6 * self.simulation_time + self.crowd.residents[animated]["phase"])) * .55 if animated is not None else None
        return {"engine": "Panda3D", "simulationTime": self.simulation_time,
                "residentCount": len(self.resident_nodes), "primitiveCount": len(self.scene["primitives"]),
                "assetLoaded": self.asset_loaded, "assetMeshCount": self.asset_mesh_count,
                "visibleResidentCount": self.crowd.visible_count, "animatedResidentCount": self.crowd.animated_count,
                "crowdPartBatches": len(self.crowd.nodes),
                "sampleAnimatedResidentId": self.crowd.residents[animated]["id"] if animated is not None else None,
                "sampleGaitAngle": gait,
                "mode": self.mode, "paused": self.paused,
                "selectedId": self.selected,
                "sampleResidentPosition": [sample.x, sample.y, sample.z]}

    def screenshot(self, path):
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.move_residents()
        self.update_hud()
        for _ in range(4):
            self.graphicsEngine.renderFrame()
        pixels = PNMImage()
        if not self.win.getScreenshot(pixels):
            raise RuntimeError("Screenshot framebuffer could not be read")
        # Encode through a stream, then use Python's native Windows path support.
        # This also works in restricted environments where Panda's direct writer fails.
        encoded = StringStream()
        if not pixels.write(encoded, destination.name):
            raise RuntimeError(f"Screenshot format could not be encoded: {destination.suffix}")
        destination.write_bytes(encoded.getData())
        return str(destination)

    def smoke_test(self):
        assert self.object_nodes and self.resident_nodes, "Fixture should populate the scene"
        self.reset()
        initial = self.get_state()["sampleResidentPosition"]
        self.advance(5)
        moved = self.get_state()["sampleResidentPosition"]
        assert initial != moved, "Resident must move at a deterministic time"
        self.paused = True
        self.advance(1)
        assert self.simulation_time == 5, "Paused simulation must not advance"
        self.paused = False
        self.toggle_speed()
        self.advance(1)
        assert self.simulation_time == 9, "4x control must multiply simulation time"
        for _, resident in self.resident_nodes.values():
            first, _ = self.route_position(resident, 0)
            wrapped, _ = self.route_position(resident, self.routes[resident["route_id"]]["duration"])
            assert (first - wrapped).length() < .001, "Routes must wrap without drift"
        camera_positions = []
        for mode in ("overhead", "walk", "follow"):
            self.set_mode(mode)
            camera_positions.append(tuple(self.camera.getPos()))
        assert len(set(camera_positions)) == 3, "Camera modes must have distinct positions"
        assert self.walk_allowed(self.walk_position.x, self.walk_position.y), "Walk spawn must be clear"
        for box in self.scene["collision_boxes"]:
            center = [(low + high) / 2 for low, high in zip(box["min"], box["max"])]
            assert not self.walk_allowed(*center), "Building interior must block walking"
        assert not self.walk_allowed(self.scene["bounds"]["max"][0] + 1, 0)
        # Exercise the same lens projection and collision ray used by mouse picking.
        actor_id = next(iter(self.resident_nodes))
        actor = self.resident_nodes[actor_id][0]
        target = actor.getPos() + Vec3(0, 0, .9)
        self.camera.setPos(target + Vec3(0, -.01, 20))
        self.camera.lookAt(target)
        projected = Point2()
        assert self.camLens.project(self.camera.getRelativePoint(self.render, target), projected)
        self.pick_at(projected.x, projected.y)
        assert self.selected == actor_id, "Rendered resident must be selectable through its camera ray"
        self.set_mode("follow")
        assert self.selected_resident == actor_id
        target = Vec3(0, 30, 77.4)
        self.camera.setPos(target + Vec3(0, -.01, 25))
        self.camera.lookAt(target)
        assert self.camLens.project(self.camera.getRelativePoint(self.render, target), projected)
        self.pick_at(projected.x, projected.y)
        assert self.selected == "city-hall", "Imported City Hall extras must resolve through its camera ray"
        self.reset()
        assert self.get_state()["sampleResidentPosition"] == initial, "Reset must reproduce initial state"
        assert self.asset_loaded and self.asset_mesh_count > 0, "Actual GLB meshes must load"
        assert len(self.crowd.nodes) == 7, "Crowd must use seven batched parts, not nodes per resident"
        assert self.crowd.animated_count <= 300
        assert 0 <= self.crowd.visible_count <= self.population
        self.set_mode("walk")
        self.move_residents()
        assert 0 < self.crowd.animated_count <= 300, "Near-camera residents must receive gait"
        before = self.get_state()["sampleGaitAngle"]
        self.simulation_time += .1
        self.move_residents()
        assert self.get_state()["sampleGaitAngle"] != before, "Submitted near-person gait must advance"
        self.simulation_time = 0
        self.move_residents()
        assert abs(self.eye_height(0, -10) - 2.28) < .001 and abs(self.eye_height(0, 4) - 4.2) < .001
        self.set_mode("overhead")
        original_population = self.population
        original_position = tuple(self.camera.getPos())
        self.set_population(1000 if original_population == 200 else 200)
        assert self.simulation_time == 0 and tuple(self.camera.getPos()) == original_position, "Population control must preserve time/camera"
        assert len(self.resident_nodes) == self.population and len(self.crowd.nodes) == 7
        self.set_population(original_population)
        for _ in range(4):
            self.graphicsEngine.renderFrame()
        return self.get_state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="Exercise the scene offscreen and exit")
    parser.add_argument("--screenshot", metavar="PATH", help="Save a rendered PNG and exit")
    parser.add_argument("--offscreen", action="store_true", help="Render without opening a desktop window")
    parser.add_argument("--mode", choices=("overhead", "walk", "follow"), default="overhead",
                        help="Initial camera mode, also used for screenshots")
    parser.add_argument("--population", type=int, choices=(200, 1000, 5000), help="Synthetic population preset")
    args = parser.parse_args()
    app = CityHallDemo(offscreen=args.offscreen or args.smoke_test or bool(args.screenshot), population=args.population)
    try:
        if args.smoke_test:
            print("PANDA3D_SMOKE_OK " + json.dumps(app.smoke_test()), flush=True)
        if args.screenshot:
            app.set_mode(args.mode)
            print("PANDA3D_SCREENSHOT " + app.screenshot(args.screenshot), flush=True)
        if not args.smoke_test and not args.screenshot:
            app.set_mode(args.mode)
            app.run()
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
