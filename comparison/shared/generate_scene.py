"""Generate the original, deterministic fixture used by every renderer demo."""

import json
import math
from pathlib import Path


def make_scene():
    scene = {
        "version": 1,
        "name": "Civic Center / City Hall",
        "description": "Original schematic geometry and scripted trips; not surveyed SF data.",
        "origin": {"longitude": -122.4193, "latitude": 37.7793},
        "bounds": {"min": [-230, -180], "max": [230, 180]},
        "camera": {"target": [0, 10, 12], "distance": 355,
                   "yaw_degrees": -65, "pitch_degrees": 48,
                   "walk_position": [0, -72, 1.8]},
        "primitives": [], "collision_boxes": [], "routes": [], "residents": [],
    }
    stone = [0.76, 0.72, 0.62]
    light_stone = [0.91, 0.86, 0.72]
    gold = [0.78, 0.62, 0.29]
    def shape(identity, kind, position, color, label=None, **dimensions):
        scene["primitives"].append(dict(id=identity, label=label or identity,
                                       kind=kind, position=position, color=color,
                                       collidable=(identity == "city-hall" or identity == "portico" or
                                           identity.startswith(("building-", "dome", "roof-", "city-hall-", "column-"))),
                                       **dimensions))
    def box(identity, position, size, color, label=None):
        shape(identity, "box", position, color, label, size=size)
    def obstacle(identity, x, y, width, depth):
        scene["collision_boxes"].append({"id": identity,
            "min": [x-width/2, y-depth/2], "max": [x+width/2, y+depth/2]})
    box("ground", [0, 0, -0.3], [460, 360, 0.6], [0.68, 0.71, 0.67], "Civic Center ground")
    for x in [-85, 85]:
        box(f"road-v-{x}", [x, 0, 0.025], [22, 360, 0.05], [0.20, 0.25, 0.29], "North-south road")
        for y in range(-165, 180, 22):
            box(f"stripe-v-{x}-{y}", [x, y, 0.075], [0.45, 9, 0.05], [0.90, 0.83, 0.54], "Road marking")
    for y in [-85, 95]:
        box(f"road-h-{y}", [0, y, 0.035], [460, 22, 0.05], [0.20, 0.25, 0.29], "East-west road")
        for x in range(-220, 230, 22):
            if abs(abs(x)-85) > 16:
                box(f"stripe-h-{y}-{x}", [x, y, 0.085], [9, 0.45, 0.05], [0.90, 0.83, 0.54], "Road marking")
    box("civic-block", [0, 5, 0.18], [144, 154, 0.3], [0.79, 0.79, 0.72], "Civic Center block")
    box("plaza", [0, -34, 0.39], [112, 55, 0.15], [0.87, 0.83, 0.71], "Civic Center plaza")
    for x in [-42, 42]:
        box(f"lawn-{x}", [x, -32, 0.53], [20, 38, 0.12], [0.30, 0.49, 0.33], "Plaza lawn")
    box("city-hall", [0, 30, 10], [90, 44, 20], stone, "City Hall — schematic landmark")
    obstacle("city-hall", 0, 30, 90, 44)
    box("city-hall-cornice", [0, 30, 21], [94, 48, 2], light_stone, "City Hall cornice")
    box("city-hall-central-roof", [0, 30, 24], [38, 34, 4], light_stone, "City Hall roof")
    shape("dome-drum", "cylinder", [0, 30, 30], light_stone, "City Hall dome drum", radius=14, height=10)
    shape("dome", "sphere", [0, 30, 36], [0.42, 0.48, 0.44], "City Hall dome", radius=15, scale=[1, 1, 1.05])
    shape("dome-crown", "cylinder", [0, 30, 51], gold, "City Hall dome crown", radius=3.3, height=7)
    shape("dome-finial", "sphere", [0, 30, 55.5], gold, "City Hall dome finial", radius=2)
    for i, x in enumerate(range(-36, 37, 9)):
        shape(f"column-{i}", "cylinder", [x, 5.5, 11], light_stone,
              "City Hall columns", radius=1.5, height=17)
    box("portico", [0, 5, 20], [80, 9, 2.5], light_stone, "City Hall portico")
    for i in range(4):
        box(f"steps-{i}", [0, -5+i*1.4, 0.5+i*0.35], [65-i*3, 12-i*2, 0.5], light_stone, "City Hall steps")
    for i, x in enumerate(range(-36, 37, 9)):
        for floor in [0, 1]:
            box(f"hall-window-{i}-{floor}", [x, 7.9, 7+floor*8], [3.3, 0.15, 4.5], [0.18, 0.29, 0.33], "City Hall window")
    buildings = [(-150,25,72,105,27), (150,25,72,105,33), (-148,138,88,48,21),
                 (-32,138,70,48,36), (48,138,60,48,24), (156,138,82,48,29),
                 (-158,-136,72,48,25),(-48,-136,58,48,19),(32,-136,68,48,29),(154,-136,82,48,39)]
    palette = [[0.67,0.62,0.55],[0.74,0.72,0.65],[0.57,0.65,0.66],[0.73,0.64,0.51]]
    for i,(x,y,w,d,h) in enumerate(buildings):
        label = ("Homes" if i % 3 == 0 else "Workplaces") + f" / block {i+1:02d}"
        box(f"building-{i}", [x,y,h/2], [w,d,h], palette[i%len(palette)], label)
        box(f"roof-{i}", [x,y,h+0.5], [w+1,d+1,1], [0.41,0.45,0.44], label+" roof")
        obstacle(f"building-{i}", x,y,w,d)
        for floor in range(1,int(h/7)):
            box(f"windows-{i}-{floor}", [x,y-d/2-0.09,floor*7], [w-8,0.18,2.5], [0.21,0.34,0.38], label+" windows")
    tree_positions = [(x,y) for x in [-63,63] for y in [-52,-28,0,65]] + [(x,-63) for x in [-40,-20,20,40]]
    for i,(x,y) in enumerate(tree_positions):
        shape(f"tree-trunk-{i}","cylinder",[x,y,2],[0.36,0.26,0.17],"Plaza tree",radius=0.65,height=4)
        shape(f"tree-crown-{i}","sphere",[x,y,6],[0.22,0.40+0.025*(i%3),0.31],"Plaza tree",radius=3.8,scale=[1,1,1.25])
    route_points = [
        [[-66,-66,0.55],[66,-66,0.55],[66,77,0.55],[-66,77,0.55],[-66,-66,0.55]],
        [[-205,-68,0.55],[205,-68,0.55],[205,-170,0.55],[-205,-170,0.55],[-205,-68,0.55]],
        [[-66,-66,0.55],[-66,112,0.55],[112,112,0.55],[112,-66,0.55],[-66,-66,0.55]],
        [[-24,-58,0.55],[24,-58,0.55],[24,-14,0.55],[-24,-14,0.55],[-24,-58,0.55]],
    ]
    for i,points in enumerate(route_points):
        length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
        scene["routes"].append({"id":f"route-{i}","label":["Civic loop","Neighborhood loop","Work commute loop","Plaza walk"][i],"points":points,"duration":round(length/5.5,6)})
    resident_colors=[[0.98,0.62,0.23],[0.16,0.67,0.69],[0.84,0.33,0.27],[0.47,0.46,0.78]]
    for i in range(120):
        scene["residents"].append({"id":f"resident-{i:03d}","label":f"Resident {i+1:03d}","route_id":f"route-{i%4}","phase":round((i*0.61803398875)%1,9),"color":resident_colors[i%4]})
    return scene


if __name__ == "__main__":
    from detailed_scene import upgrade_scene
    destination=Path(__file__).with_name("scene.json")
    destination.write_text(json.dumps(upgrade_scene(make_scene()),indent=2)+"\n",encoding="utf-8")
    print(f"Generated {destination.name}")
