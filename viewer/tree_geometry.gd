extends RefCounted
## Three original unit-height silhouettes, independent of measured tree dimensions.
const Builder = preload("res://geography_mesh.gd")
const BARK := Color("756351")
const LEAF := Color("57784e")

static func create_mesh(shape: String) -> ArrayMesh:
	var builder = Builder.new()
	_cylinder(builder,0.027,0.55 if shape != "palm" else 0.87,6)
	match shape:
		"conifer":
			_cone(builder,0.18,0.60,0.5,8)
			_cone(builder,0.39,0.81,0.37,8)
			_cone(builder,0.61,1.0,0.24,8)
		"palm":
			for i: int in range(8):
				var angle: float = float(i)*TAU/8.0
				var direction := Vector3(cos(angle),0,sin(angle))
				var side := Vector3(-sin(angle),0,cos(angle))*0.072
				var base := Vector3(0,0.85,0)
				var middle: Vector3 = direction*0.27+Vector3.UP
				var tip: Vector3 = direction*0.5+Vector3.UP*0.82
				for face: Array in [[base,middle-side,middle],[base,middle,middle+side],[middle-side,tip,middle],[middle,tip,middle+side]]:
					builder.triangle(face[0],face[1],face[2],LEAF,Vector3.UP)
					builder.triangle(face[0],face[2],face[1],LEAF,Vector3.DOWN)
		_:
			var center := Vector3(0,0.68,0)
			for latitude: int in range(4):
				var lower: float = -PI*0.5+float(latitude)*PI/4.0
				var upper: float = lower+PI/4.0
				for longitude: int in range(8):
					var a: float = float(longitude)*TAU/8.0
					var b: float = float(longitude+1)*TAU/8.0
					var points: Array[Vector3] = [_sphere_point(a,lower,center),_sphere_point(b,lower,center),_sphere_point(b,upper,center),_sphere_point(a,upper,center)]
					for face: Array in [[points[0],points[1],points[2]],[points[0],points[2],points[3]]]:
						if (face[1]-face[0]).cross(face[2]-face[0]).length_squared() < 0.00000001: continue
						builder.triangle(face[0],face[1],face[2],LEAF,((face[0]+face[1]+face[2])/3.0-center).normalized())
	var instance: MeshInstance3D = builder.create_instance("UnitTree",null)
	var result: ArrayMesh = instance.mesh
	instance.free()
	return result

static func _sphere_point(angle: float, latitude: float, center: Vector3) -> Vector3:
	return center+Vector3(cos(angle)*cos(latitude)*0.5,sin(latitude)*0.32,sin(angle)*cos(latitude)*0.5)

static func _cylinder(builder: RefCounted, radius: float, height: float, count: int) -> void:
	for i: int in range(count):
		var a := Vector3(cos(float(i)*TAU/count)*radius,0,sin(float(i)*TAU/count)*radius)
		var b := Vector3(cos(float(i+1)*TAU/count)*radius,0,sin(float(i+1)*TAU/count)*radius)
		var normal: Vector3 = (a+b).normalized()
		builder.triangle(a,b,b+Vector3.UP*height,BARK,normal)
		builder.triangle(a,b+Vector3.UP*height,a+Vector3.UP*height,BARK,normal)

static func _cone(builder: RefCounted, base: float, top: float, radius: float, count: int) -> void:
	for i: int in range(count):
		var a := Vector3(cos(float(i)*TAU/count)*radius,base,sin(float(i)*TAU/count)*radius)
		var b := Vector3(cos(float(i+1)*TAU/count)*radius,base,sin(float(i+1)*TAU/count)*radius)
		builder.triangle(a,b,Vector3.UP*top,LEAF,Vector3(a.x+b.x,radius,a.z+b.z).normalized())
		builder.triangle(a,Vector3.UP*base,b,LEAF,Vector3.DOWN)
