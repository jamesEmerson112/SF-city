"""Original architectural study and common crowd data for round two."""
import math

CLOTHES = [[0.88, 0.48, 0.17], [0.12, 0.43, 0.46], [0.65, 0.22, 0.17], [0.35, 0.32, 0.55]]
SKINS = [[0.63, 0.39, 0.25], [0.87, 0.67, 0.49], [0.38, 0.23, 0.16], [0.74, 0.51, 0.34]]


def create_residents(count):
    return [{"id": f"resident-{i:03d}", "label": f"Resident {i+1:03d}",
             "route_id": f"route-{i%4}", "phase": (i * 0.61803398875) % 1,
             "color": CLOTHES[i % 4], "skin_color": SKINS[(i // 3) % 4],
             "trouser_color": [[0.08, 0.12, 0.18], [0.21, 0.22, 0.20]][i % 2],
             "bag_color": [[0.30, 0.21, 0.12], [0.15, 0.18, 0.20]][i % 2],
             "home": f"Home block {i%10+1:02d}", "destination": "City Hall" if i % 4 == 3 else f"Work block {(i*3)%10+1:02d}"}
            for i in range(count)]


def upgrade_scene(scene):
    scene.update(version=2, name="City Hall / Morning rush", description="Original Blender architectural study; synthetic population workloads.")
    scene["asset"] = {"file": "civic-center.glb", "url": "/scene-assets/civic-center.glb", "authoring_file": "civic-center.blend"}
    scene["population_presets"] = [200, 1000, 5000]
    scene["resident_palette"] = CLOTHES
    scene["skin_palette"] = SKINS
    scene["residents"] = create_residents(200)
    scene["character"] = {
        "animation_distance": 80, "max_animated": 300, "height": 1.73,
        "parts": [
            {"id": "torso", "kind": "box", "size": [0.27, 0.46, 0.62], "center": [0, 0, 1.08], "color_role": "clothes"},
            {"id": "head", "kind": "sphere", "radius": 0.15, "center": [0, 0, 1.58], "color_role": "skin"},
            {"id": "left-arm", "kind": "box", "size": [0.13, 0.13, 0.58], "center": [0, 0.31, 1.06], "pivot": [0, 0.31, 1.35], "swing": 1, "color_role": "clothes"},
            {"id": "right-arm", "kind": "box", "size": [0.13, 0.13, 0.58], "center": [0, -0.31, 1.06], "pivot": [0, -0.31, 1.35], "swing": -1, "color_role": "clothes"},
            {"id": "left-leg", "kind": "box", "size": [0.17, 0.18, 0.76], "center": [0, 0.135, 0.41], "pivot": [0, 0.135, 0.79], "swing": -1, "color_role": "trousers"},
            {"id": "right-leg", "kind": "box", "size": [0.17, 0.18, 0.76], "center": [0, -0.135, 0.41], "pivot": [0, -0.135, 0.79], "swing": 1, "color_role": "trousers"},
            {"id": "backpack", "kind": "box", "size": [0.16, 0.34, 0.40], "center": [-0.205, 0, 1.13], "color_role": "bag"},
        ],
    }
    scene["camera"].update(target=[0, 15, 22], distance=330, pitch_degrees=39, yaw_degrees=-72, walk_position=[-9, -44, 2.28], walk_pitch_degrees=18)
    scene["walk_surfaces"] = [{"min": [-30, -10], "max": [30, 4], "from_y": -10, "to_y": 4, "from_z": 0.48, "to_z": 2.4}]
    # Keep the familiar district footprint while replacing its landmark silhouette.
    scene["primitives"] = [p for p in scene["primitives"] if not p["id"].startswith(("dome", "steps-", "column-", "hall-window-", "city-hall-central-roof", "portico"))]
    stone = [0.63, 0.59, 0.49]
    trim = [0.82, 0.78, 0.67]
    dark = [0.08, 0.16, 0.19]
    bronze = [0.36, 0.28, 0.16]
    gold = [0.64, 0.46, 0.14]

    def shape(identity, kind, position, color, label, group="city-hall", **dimensions):
        scene["primitives"].append({"id": identity, "label": label, "kind": kind,
            "position": list(position), "color": color, "collidable": group == "city-hall" or group.startswith("building-"),
            "group": group, **dimensions})

    def box(identity, position, size, color=stone, label="City Hall facade", group="city-hall", **options):
        shape(identity, "box", position, color, label, group, size=list(size), **options)

    def cylinder(identity, position, radius, height, color=trim, label="City Hall detail", group="city-hall", **options):
        shape(identity, "cylinder", position, color, label, group, radius=radius, height=height, **options)

    # Layered rooflines, pilasters, window reveals, and rusticated basement courses.
    box("hall-foundation", [0, 29, 1.15], [94, 46, 2.3], stone)
    for level, z in enumerate([2.4, 6.0, 13.8, 20.2, 22.0]):
        box(f"hall-course-{level}", [0, 30, z], [94.5, 47, 0.35], trim)
    for x in range(-42, 43, 7):
        box(f"pilaster-{x}", [x, 7.8, 12.8], [1.15, 0.8, 13.4], trim)
        box(f"pilaster-capital-{x}", [x, 7.7, 19.4], [1.8, 1.15, 0.55], trim)
    for index, x in enumerate(range(-38, 39, 7)):
        for floor, z in enumerate([4.2, 9.1, 16.4]):
            box(f"reveal-{index}-{floor}", [x, 7.68, z], [3.6, 0.48, 3.45], bronze)
            box(f"glass-{index}-{floor}", [x, 7.36, z], [2.9, 0.12, 2.95], dark, metallic=0.35, roughness=0.13)
            box(f"sill-{index}-{floor}", [x, 7.2, z-1.55], [3.8, 0.9, 0.26], trim)
            box(f"lintel-{index}-{floor}", [x, 7.25, z+1.65], [3.8, 0.8, 0.30], trim)
            box(f"mullion-{index}-{floor}", [x, 7.24, z], [0.14, 0.24, 3.0], bronze)
            box(f"transom-{index}-{floor}", [x, 7.20, z+0.4], [3, 0.25, 0.12], bronze)
    for side in [-1, 1]:
        for row, y in enumerate(range(13, 51, 6)):
            for floor, z in enumerate([8.5, 16.2]):
                box(f"side-window-{side}-{row}-{floor}", [side*45.08, y, z], [0.18, 2.8, 3.5], dark, roughness=0.15)
                box(f"side-sill-{side}-{row}-{floor}", [side*45.15, y, z-1.8], [0.55, 3.3, 0.25], trim)
    for i in range(13):
        y = -10 + i * 1.08
        box(f"entrance-step-{i}", [0, y, 0.48+(i+1)*0.074], [61-i*0.12, 1.14, (i+1)*0.148], trim, "City Hall entrance staircase")
    for i, x in enumerate([-24, -16, -8, 8, 16, 24]):
        cylinder(f"column-base-{i}", [x, 3.5, 2.7], 1.55, 0.65)
        cylinder(f"column-shaft-{i}", [x, 3.5, 10.8], 0.98, 15.5)
        for flute in range(12):
            angle = flute * math.tau / 12
            cylinder(f"flute-{i}-{flute}", [x+0.99*math.cos(angle), 3.5+0.99*math.sin(angle), 10.8], 0.10, 14.8, stone)
        cylinder(f"column-neck-{i}", [x, 3.5, 18.5], 1.2, 0.45)
        box(f"column-capital-{i}", [x, 3.5, 19], [2.8, 2.8, 0.65], trim)
    box("portico", [0, 3.3, 20.4], [61, 8.0, 2], trim, "City Hall entrance portico")
    # A triangular pediment and a two-tier drum create a distinct landmark shape.
    shape("entrance-pediment", "pediment", [0, 3, 21.4], trim, "City Hall pediment", width=63, depth=8.3, height=7.2)
    for i, x in enumerate([-12, 0, 12]):
        box(f"entry-door-{i}", [x, 7.18, 5.1], [4.0, 0.22, 5.3], bronze, "City Hall doorway", roughness=0.4)
        for offset in [-0.92, 0.92]:
            box(f"door-glass-{i}-{offset}", [x+offset, 7.02, 5.7], [1.55, 0.10, 3.1], dark, roughness=0.1, metallic=0.45)
    box("central-roof-plinth", [0, 30, 24.0], [42, 36, 5.0], trim)
    cylinder("drum-base", [0, 30, 28], 17.2, 2.0)
    cylinder("lower-drum", [0, 30, 34], 15.7, 10.5, stone)
    for i in range(20):
        angle = i * math.tau / 20
        x, y = 15.8*math.cos(angle), 30+15.8*math.sin(angle)
        cylinder(f"drum-column-{i}", [x, y, 34.1], .6, 10.5)
        box(f"drum-window-{i}", [15.55*math.cos(angle), 30+15.55*math.sin(angle), 34], [0.4, 1.5, 5.8], dark, rotation=[0, 0, math.degrees(angle)])
    cylinder("drum-cornice", [0, 30, 39.6], 17.5, 1.4)
    cylinder("upper-drum", [0, 30, 42.0], 13.9, 4, stone)
    # Lathed dome profile provides height and curvature rather than a full sphere.
    profile = [[14.6, 0], [14.5, 2], [13.9, 5], [12.6, 9], [10.8, 13], [8.3, 17], [5.2, 20], [3.1, 22]]
    shape("dome-shell", "lathe", [0, 30, 44], [0.28, 0.34, 0.31], "City Hall dome", profile=profile, metallic=0.4, roughness=0.45)
    for i in range(24):
        angle = i*math.tau/24
        points = [[(radius+0.16)*math.cos(angle), 30+(radius+0.16)*math.sin(angle), 44+height] for radius,height in profile]
        shape(f"dome-rib-{i}", "tube", [0, 0, 0], gold, "City Hall gilded dome rib", points=points, radius=0.11, metallic=0.75)
    cylinder("lantern-base", [0, 30, 66.4], 3.8, 1.2, gold, metallic=0.75)
    cylinder("lantern", [0, 30, 69.5], 2.7, 5.0, trim)
    for i in range(8):
        angle=i*math.tau/8
        cylinder(f"lantern-column-{i}", [2.8*math.cos(angle), 30+2.8*math.sin(angle), 69.5], .2, 5, gold, metallic=.7)
    shape("lantern-cupola", "sphere", [0, 30, 72.2], gold, "City Hall lantern", radius=3.1, scale=[1,1,.65], metallic=.75)
    cylinder("finial", [0, 30, 75], .25, 4.5, gold, metallic=.8)
    shape("finial-orb", "sphere", [0,30,77.4], gold, "City Hall finial", radius=.58, metallic=.8)
    # Rooftop balustrades; a handful of repeating details makes the facade readable.
    for side in [-1,1]:
        for i, x in enumerate(range(-44,45,2)):
            cylinder(f"baluster-{side}-{i}", [x,30+side*23,23], .16, 1.4, trim)
        box(f"balustrade-{side}",[0,30+side*23,23.9],[91,0.8,.3],trim)
    # Fine pavement grid with deliberate spacing, unlike coplanar decal layers.
    for x in range(-54,55,6):
        box(f"paving-joint-x-{x}", [x,-34,.482], [.035,53,.018], [0.48,.48,.43], "Plaza paving joint", "plaza")
    for y in range(-60,-7,6):
        box(f"paving-joint-y-{y}", [0,y,.482], [109,.035,.018], [0.48,.48,.43], "Plaza paving joint", "plaza")
    # Benches, lamp posts, bollards and zebra crossings provide human scale.
    for i,(x,y) in enumerate([(x,y) for x in [-29,29] for y in [-49,-29,-14]]):
        for slat in range(4):
            box(f"bench-seat-{i}-{slat}",[x,y+slat*.13,.95],[2.0,.11,.11],[.30,.19,.10],"Plaza bench",f"furniture-{i}")
            box(f"bench-back-{i}-{slat}",[x,y+.51,1.16+slat*.13],[2.0,.10,.11],[.30,.19,.10],"Plaza bench",f"furniture-{i}")
        for side in [-.75,.75]:
            box(f"bench-leg-{i}-{side}",[x+side,y+.2,.69],[.1,.65,.48],[.08,.11,.12],"Plaza bench",f"furniture-{i}",metallic=.6)
    for i,(x,y) in enumerate([(x,y) for x in [-69,69] for y in [-58,-5,66]]):
        cylinder(f"lamp-base-{i}",[x,y,.82],.30,.65,bronze,"Street lamp",f"lamp-{i}")
        cylinder(f"lamp-post-{i}",[x,y,3.4],.12,5.7,bronze,"Street lamp",f"lamp-{i}",metallic=.7)
        box(f"lamp-housing-{i}",[x,y,6.55],[.7,.7,.8],bronze,"Street lamp",f"lamp-{i}")
        box(f"lamp-glass-{i}",[x,y-.36,6.55],[.52,.03,.58],[.95,.79,.43],"Street lamp",f"lamp-{i}",emission=.35)
    for i,x in enumerate(range(-30,31,5)):
        cylinder(f"bollard-{i}",[x,-67,1.12],.18,1.2,bronze,"Plaza bollard","street-furniture",metallic=.65)
    cylinder("fountain-base",[0,-34,.75],5.8,.55,stone,"Plaza fountain","fountain")
    cylinder("fountain-water",[0,-34,1.045],5.3,.08,[.10,.30,.32],"Plaza fountain","fountain",metallic=.45,roughness=.12)
    cylinder("fountain-pedestal",[0,-34,1.65],.85,1.3,trim,"Plaza fountain","fountain")
    cylinder("fountain-bowl",[0,-34,2.32],2.1,.24,stone,"Plaza fountain","fountain")
    for i,(x,y) in enumerate([(-91,-34),(-91,28),(91,14),(91,61),(-40,-91),(120,-91)]):
        car_color=[[.18,.26,.32],[.55,.16,.12],[.73,.70,.61]][i%3]
        group=f"parked-car-{i}"
        box(f"car-body-{i}",[x,y,.83],[1.85,4.3,.7],car_color,"Parked vehicle",group,roughness=.3,metallic=.25)
        box(f"car-cabin-{i}",[x,y,1.38],[1.55,2.25,.65],dark,"Parked vehicle",group,roughness=.12,metallic=.3)
        box(f"car-roof-{i}",[x,y,1.75],[1.62,2.3,.13],car_color,"Parked vehicle",group,roughness=.3)
        for axle in [-1.35,1.35]:
            for side in [-.91,.91]:
                cylinder(f"wheel-{i}-{axle}-{side}",[x+side,y+axle,.5],.38,.18,[.035,.04,.045],"Parked vehicle",group,rotation=[0,90,0])
    for direction,x,y in [(0,-85,-65),(0,85,-65),(1,-65,-85),(1,65,95)]:
        for i in range(9):
            pos=[x,y+(i-4)*1.7,.135] if direction==0 else [x+(i-4)*1.7,y,.145]
            size=[20,.72,.03] if direction==0 else [.72,20,.03]
            box(f"crosswalk-{x}-{y}-{i}",pos,size,[.89,.88,.79],"Pedestrian crossing","crosswalks")
    # Give neighboring buildings individual window bays and parapets.
    buildings = [p for p in scene["primitives"] if p["id"].startswith("building-")]
    for building in buildings:
        x,y,z=building["position"]; w,d,h=building["size"]; identity=building["id"]
        for row in range(1,int(h/5)):
            for column in range(max(1,int((w-8)/5))):
                wx=x-w/2+5+column*5
                box(f"bay-{identity}-{row}-{column}",[wx,y-d/2-.19,row*5],[2.5,.18,2.8],dark,building["label"],identity,roughness=.18)
                box(f"bay-sill-{identity}-{row}-{column}",[wx,y-d/2-.28,row*5-1.5],[2.9,.45,.18],trim,building["label"],identity)
        box(f"parapet-front-{identity}",[x,y-d/2,h+1.1],[w,.7,1.4],stone,building["label"],identity)
    # Realistic walking pace, kept deterministic and independent of population.
    for route in scene["routes"]:
        route["duration"] = sum(math.dist(a,b) for a,b in zip(route["points"],route["points"][1:])) / 1.45
    scene["source_note"] = "Original stylized architecture inspired by City Hall, not a surveyed reconstruction. Synthetic crowd workloads."
    return scene
