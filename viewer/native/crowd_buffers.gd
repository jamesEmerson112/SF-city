extends RefCounted
## Portable baseline for the optional native helper. It only packs draw inputs.
const MAX_INSTANCES: int = 100000
const MAX_PARTS: int = 32
const STRIDE: int = 20
var part_colors: Array[PackedColorArray] = []
var error_message: String = ""

func get_error_message() -> String:
	return error_message

func protocol_version() -> int:
	return 1

func configure_colors(colors: Array[PackedColorArray]) -> bool:
	error_message = ""
	if colors.size() > MAX_PARTS:
		error_message = "Crowd part count exceeds its bound."
		return false
	var count: int = colors[0].size() if not colors.is_empty() else 0
	if count > MAX_INSTANCES:
		error_message = "Crowd instance count exceeds its bound."
		return false
	for values: PackedColorArray in colors:
		if values.size() != count:
			error_message = "Crowd part colors do not share stable slot membership."
			return false
	part_colors = []
	for values: PackedColorArray in colors:
		part_colors.append(values.duplicate())
	return true

func build_buffers(roots: Array[Transform3D], custom: PackedColorArray) -> Array[PackedFloat32Array]:
	error_message = ""
	var result: Array[PackedFloat32Array] = []
	if roots.size() > MAX_INSTANCES or custom.size() != roots.size() or (not part_colors.is_empty() and part_colors[0].size() != roots.size()):
		error_message = "Crowd transforms, flags and colors do not share stable slots."
		return result
	if part_colors.is_empty():
		return result
	var base := PackedFloat32Array()
	base.resize(roots.size() * STRIDE)
	for index: int in range(roots.size()):
		var pose: Transform3D = roots[index]
		var flags: Color = custom[index]
		var offset: int = index * STRIDE
		# RenderingServer's documented row-major Transform3D layout.
		base[offset] = pose.basis.x.x
		base[offset+1] = pose.basis.y.x
		base[offset+2] = pose.basis.z.x
		base[offset+3] = pose.origin.x
		base[offset+4] = pose.basis.x.y
		base[offset+5] = pose.basis.y.y
		base[offset+6] = pose.basis.z.y
		base[offset+7] = pose.origin.y
		base[offset+8] = pose.basis.x.z
		base[offset+9] = pose.basis.y.z
		base[offset+10] = pose.basis.z.z
		base[offset+11] = pose.origin.z
		base[offset+16] = flags.r
		base[offset+17] = flags.g
		base[offset+18] = flags.b
		base[offset+19] = flags.a
	for colors: PackedColorArray in part_colors:
		var buffer: PackedFloat32Array = base.duplicate()
		for index: int in range(colors.size()):
			var tint: Color = colors[index]
			var offset: int = index * STRIDE + 12
			buffer[offset] = tint.r
			buffer[offset+1] = tint.g
			buffer[offset+2] = tint.b
			buffer[offset+3] = tint.a
		result.append(buffer)
	return result
