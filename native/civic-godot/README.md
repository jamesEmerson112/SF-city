# Optional native crowd buffers

This small Rust GDExtension packs already-computed crowd transforms, colors and
custom shader flags into MultiMesh buffers. It does not own resident identities,
simulation state, camera following, picking, visibility decisions or gait math.
GDScript keeps those decisions and the shader keeps the same gait expression.

`CivicCrowdBuffers.configure_colors(Array[PackedColorArray])` freezes per-part
appearance in the caller's stable slot order. `build_buffers(Array[Transform3D],
PackedColorArray)` returns one `PackedFloat32Array` per part. Each instance has
20 floats: row-major transform (12), RGBA tint (4), and custom flags (4). This is
the [documented RenderingServer layout](https://docs.godotengine.org/en/stable/classes/class_renderingserver.html#class-renderingserver-method-multimesh-set-buffer).
Inputs are bounded to 100,000 instances and 32 parts; this is an allocation guard,
not an increase to supported live population. Inconsistent slot counts return
an empty result/error and never partially change appearance configuration.

The current upstream release observed September 6, 2026 is
[godot-rust 0.5.5](https://github.com/godot-rust/gdext/releases/tag/v0.5.5).
Its [manifest requires Rust 1.94](https://github.com/godot-rust/gdext/blob/v0.5.5/Cargo.toml).
This prototype pins `godot=0.4.5` and API 4.5 to work with the installed Rust
1.92 compiler. It only needs builtin values and RefCounted, so full scene-class
code generation is disabled. The bindings' documented rule is
[API version <= runtime version](https://godot-rust.github.io/book/toolchain/godot-version.html).
The resulting Windows x86_64 DLL was actually loaded and tested with the project's
official Godot 4.7.2 runtime, with balanced Rust safeguard checks enabled.

Build from the repository root:

```powershell
venv/Scripts/python.exe native/civic-godot/build.py --fetch
# Subsequent builds use only the locked local Cargo cache.
venv/Scripts/python.exe native/civic-godot/build.py
```

Cargo dependencies stay in `.cache/cargo-godot`; build output stays in
`.cache/civic-godot`. The script stages the optional DLL, extension descriptor and
source/binary checksum manifest under `viewer/native`. Generated files are
ignored by Git. The build requires an appropriate linker (MSVC on Windows).
Source, `Cargo.lock`, and the descriptor template are retained here for
reproduction. No global Rust toolchain or packaged viewer is modified.

`viewer/native/crowd_buffer_factory.gd` can select the helper. The default `auto`
uses an installed compatible extension and returns null when it is absent, so
the original per-instance GDScript path can run. `CIVIC_CROWD_BACKEND=individual`
forces that path; `rust` requests the helper explicitly; `gdscript` selects the
portable bulk-packing baseline for comparison. A load/protocol error is reported.
Callers must retain the previous valid buffers if a helper rejects input. All
extension calls stay on the main thread; no experimental Rust threading mode is
enabled. The helper returns detached buffers and never mutates caller inputs.

Validation commands:

```powershell
comparison/.tools/godot/Godot_v4.7.2-stable_win64_console.exe --headless --path viewer --script res://native/crowd_buffer_tests.gd -- --require-native
comparison/.tools/godot/Godot_v4.7.2-stable_win64_console.exe --path viewer --rendering-method gl_compatibility --script res://native/crowd_buffer_benchmark.gd
```

The rendered benchmark compares every buffer with Godot's real per-instance
uploads, including nontrivial rotations, zero-scale hidden roots, tint, selection
and gait flags. Headless mode has a dummy renderer, so GPU upload parity is
checked in rendered mode. The fixture uses 1,000 slots, 880 changing transforms
and seven parts; after 10 warmups it interleaves 100 samples per method.

| Packing and upload path | Median | p95 |
|---|---:|---:|
| Current style: 880 changing roots, existing colors/custom | 1.281 ms | 1.979 ms |
| Individual roots and custom for all 1,000 slots | 2.896 ms | 3.808 ms |
| GDScript bulk packing plus seven uploads | 2.930 ms | 5.046 ms |
| Rust bulk packing plus seven uploads | 0.454 ms | 0.763 ms |

These local measurements used Godot 4.7.2/OpenGL Compatibility on a GTX 1070 Ti;
the log is `.cache/crowd-buffer-benchmark.log`. Native packing saves about
0.83 ms median against the current changing-root uploads, not the whole ~21 ms
crowd phase measured in the city viewer. Pose/record/LOD loops remain GDScript
costs. A whole-viewer comparison is needed before attributing an FPS change to
this helper. The GDScript bulk baseline is slower than the existing fallback.

The helper source is MIT licensed. godot-rust's crates are MPL-2.0; their source
is available from the pinned crate archives and
[upstream v0.4.5](https://github.com/godot-rust/gdext/tree/v0.4.5).
Other dependency versions and registry checksums are in `Cargo.lock`.
The portable builder verifies these inputs and includes all 22 unchanged source
archives (8,039,226 bytes), their original notices, the official MPL-2.0 text,
and a `licenses/native-crowd/SOURCES.json` mapping of source paths, registry URLs,
licenses and SHA256 values. Nanoserde-derive's archive omits a standalone notice;
the builder uses the paired nanoserde workspace MIT text after checking that
their recorded Git revisions match. The complete original source archives retain
all embedded copyright notices. `--without-native` omits both native components
and uses the existing Python/GDScript paths.
