# Portable Windows development build

The local builder includes a private Python runtime, the tested Godot executable,
application code, runtime models and prepared San Francisco geography. Users do
not need a Python environment, Godot installation or Blender to run the folder.
This is a development distribution, not an installer or a signed release.

```powershell
venv/Scripts/python.exe scripts/package_civic_windows.py --download-runtime --zip
```

The first run downloads the official Python 3.13.15 x64 embeddable archive and
checks its SHA256 against the pinned [official release manifest](https://www.python.org/ftp/python/3.13.15/windows-3.13.15.json).
The same `--download-runtime` flag also permits first-time downloads of two pinned
monitoring wheels: [psutil 7.2.2](https://pypi.org/project/psutil/7.2.2/) and
[NVIDIA's nvidia-ml-py 13.610.43](https://pypi.org/project/nvidia-ml-py/13.610.43/).
Their exact filenames, PyPI metadata URLs and SHA256 values are recorded in
`scripts/package_monitoring.py` and `.cache/civic-package/hardware-wheels.json`.
The Windows x64 psutil wheel uses CPython's stable ABI; the NVIDIA binding is
pure Python. The builder does not copy another interpreter's installed binaries.

Later builds use the verified cache and need no network. The engine comes from
the tested local Godot download. Python's [embedded distribution](https://docs.python.org/3.13/using/windows.html#the-embeddable-package)
keeps its imports inside the bundle, including `runtime/python/Lib/site-packages`.
The builder preserves complete wheel contents, distribution metadata and license
notices, and checks imports with the bundled interpreter before proceeding.
Optional GIS preparation dependencies are not required to run the application.

New portable builds include local CPU, memory, storage and process reporting,
plus NVIDIA GPU reporting where the receiving machine's driver and sensors
support it. No GPU driver is installed by the package. Unavailable GPU or sensor
readings remain explicitly unavailable in the run log; they do not prevent the
application from starting. Older output folders keep their original contents
and need a fresh build to include these monitoring dependencies.

New builds also include the live Performance console. Press **F3** to view
charts, supported hardware readings and filterable logs. **Open run log** opens
the JSON report under the folder's `.local/civic/logs/`; **Record point** adds an
aggregate comparison point. The launcher supplies the local diagnostics feed
using the bundled monitoring libraries. Missing drivers/sensors show unavailable
readings, and a disconnected feed leaves local viewer metrics usable.

`package-manifest.json` records the monitoring wheel identities and notice paths
under `monitoring`, the cached archive hashes under `build_inputs`, and hashes
every extracted file. These checks cover the bundled monitoring libraries as
well as the application.

Each build gets a new folder under `dist/`. Existing folders are preserved.
Use `--output dist/my-build` to name a fresh folder or `--pilot-only` for the
smaller stylized scene. A full city build requires the completed geography import;
terrain and the visual sidecar are included when present. The initial complete
folder measured about 626 MB before ZIP compression, including the full Godot
binary. Godot also supports a smaller export-template release in a future build
stage; this folder follows its documented [PC distribution approach](https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html).

Prepared land-use colors/inspection records, named destinations and polygon
boundaries, landmark exteriors and the optional replacement street-tree inventory
are also copied with their source identities. The tree sidecar adds about 67.45 MB
of tile records before compression. These newer layers were not present in the
initial 626 MB size measurement; each new package reports its own exact size.

Open `Start San Francisco.cmd` in the output folder. A loading window shows
progress while the selected resident cohort and scenery prepare. The first cohort
build can take roughly a minute with terrain.
Subsequent launches reuse matching source data and generator code. A cached city's
internal source paths are rebased if the folder moves. Explicit scenario inputs
and saved checkpoints retain their source identity and are not rewritten.

In **Performance**, enter a population **Target** and choose **Apply live** to add
or remove synthetic residents without starting a new day. The current clock,
pause/speed settings and surviving residents remain intact. The advertised
1-5,000 target range supports load experiments; it is not a tested interactive
capacity guarantee. The older **Restart with** control still creates a new day.

The window supports resizing, maximizing and **F11** fullscreen. The Performance
panel offers window modes and UI scales of 100%, 125% and 150%; it moves between a
right dock and a bottom drawer as space changes. Display preferences are stored
in Godot's local user data on the receiving machine, separately from saved
simulation days. Use `--no-display-settings` for a launch that neither reads nor
writes those preferences. Existing distribution folders gain these features only
when rebuilt from the updated sources.

Prepared building, road and terrain arrays can also travel with a city build.
Prepare them from the current sources, then explicitly include that directory:

```powershell
venv/Scripts/python.exe -m civic_center.prepare_scenery --scope city-hall
venv/Scripts/python.exe scripts/package_civic_windows.py --render-cache .local/civic/render-cache
```

The optional `--render-cache PATH` copies only complete `.sfmesh` entries after
checking their bounded binary headers, content keys and payload SHA256 values.
The builder validates the selected entries before copying them and records their
file hashes in `package-manifest.json`. It retains the geographic source manifests
and attribution through the normal city-data copy. This option requires a city
build; it cannot accompany `--pilot-only`.

Without `--render-cache`, no existing scenery cache is shipped. Runtime cache keys
still check the current data, builder code, Godot version and rendering settings,
so an older prepared entry is ignored and regenerated when those inputs change.
Preparation reduces geometry construction during loading; GPU uploads and the
live resident simulation still run on the receiving machine. These caches do not
contain saved days or resident state.

The launch script accepts the same arguments as the repository application:

```powershell
& '.\Start San Francisco.cmd' --population 20 --mode follow
& '.\Start San Francisco.cmd' --world city --location city
& '.\Start San Francisco.cmd' --performance --window-size 1920x1080 --ui-scale 1.25
runtime/python/python.exe -m civic_center --population 200 --headless --smoke-test
runtime/python/python.exe -m civic_center.package_verify
```

`package-manifest.json` records every shipped file's size and SHA256. Integrity
verification detects absent or altered files while allowing new saves and caches.
It does not authenticate a public publisher. Python/Godot license texts and the
engine's compiled third-party attribution are included, along with geographic
source notes. No user's saved days, raw geographic download cache or Blender authoring file
is copied into the distribution.

Optional native components are included only when their local builds are present
and current. Build routing with `scripts/build_civic_native.py` and the Godot
crowd helper with `native/civic-godot/build.py` (use `--fetch` once to populate its
pinned Cargo cache). The package checks source hashes, binary hashes, and the
crowd descriptor against their build stamps. A partial, altered or stale native
build stops packaging with a rebuild instruction. Neither the compiler nor
installed system runtimes are upgraded by this step.

`--without-native` omits both the routing DLL and the crowd DLL/descriptor/stamp.
The Python routing code and original individual MultiMesh GDScript uploads stay
available, and the crowd factory treats an absent descriptor as an ordinary
fallback. The portable runtime discovers only its own native locations unless
the caller explicitly configures an external override. For a clean fallback
test, leave `CIVIC_ROUTING_DLL`, `CIVIC_ROUTING_BACKEND`, and
`CIVIC_CROWD_BACKEND` unset.

The crowd DLL uses pinned godot-rust 0.4.5/API 4.5, tested in Godot 4.7.2 with
Rust 1.92. Its package contains the helper's source/build files, complete unchanged
source archives for all 22 locked dependencies (about 8.04 MB), original
dependency notices, and Mozilla's [MPL-2.0 license text](https://www.mozilla.org/media/MPL/2.0/index.txt).
`licenses/native-crowd/SOURCES.json` maps dependency versions, declared licenses,
archive SHA256 values, registry source URLs, and packaged source paths. This
provides offline access to the covered source as described in
[MPL section 3.2](https://www.mozilla.org/en-US/MPL/2.0/#distribution-of-executable-form).
The derive subcrate's missing standalone notice is taken from the paired
nanoserde workspace archive only after their Git revisions match.

`package-manifest.json` adds `native_routing`, `native_crowd`, and `build_inputs`.
The last field records workspace-relative source/stamp/archive hashes and the
packager hash; inputs are checked again before the manifest is finalized.
Together with every shipped file's hash, the native stamp and dependency lock
make the chosen build inputs independently inspectable. These checks establish
local consistency, not a signed compiler attestation or a public publisher.

The September 6 native-packaging checks used two fresh pilot folders. Each
folder's own Python 3.13.15 ran the live worker/Godot smoke with 20 residents;
both exited successfully and passed file verification afterward. Separate model
checks selected Rust routing in the native folder and Python routing in the
fallback folder. Godot helper tests selected native=true and native=false,
respectively, with exact pose/flag and slot-reordering checks.

| Local validation folder | Shipped files / bytes | Build-input hashes | Live crowd backend |
|---|---:|---:|---|
| `dist/portable-crowd-native-check-01` | 204 / 218,135,336 | 126 | Rust |
| `dist/portable-crowd-fallback-check-01` | 135 / 208,811,843 | 88 | Individual GDScript |

Their manifest SHA256 values are
`5b01bed02a31950ba7318e99113d71f0ee51564004895ec91ba6e0ed37133b0e`
and `d5c1e41ad2f868ae0135557ed0ed58bd8cff35b4780e4dbbe0a8e7eb12f2f2de`.
The machine-readable report is `.cache/portable-crowd-validation.json`.
These checks validate optional native packaging and its genuine fallback; the
final city distribution still needs its own city data/rendered smoke evidence.

A fresh live-workspace pilot build at `dist/live-workspace-final-20260906`
was also validated with its own Python 3.13.15 and Godot 4.7.2 in a rendered window.
The trial grew the paused population from 20 to 35 with survivor/occupancy parity,
grew it to 36 while running, removed the followed newcomer when shrinking to 20,
then saved, restored and resized to 21. The run completed with zero application
or hardware errors, using the individual GDScript crowd fallback.

Post-run integrity verification passed for all 262 shipped files, totaling
210,367,131 bytes. The manifest SHA256 is
`b69b448e2885ccd320bdd475a08bf3c5080be0cca7a1e3974d0a7345a0bc819b`.
The local report and rendered capture are under
`.cache/live-workspace/portable-final/`, with the checks and manifest result in
`summary.json`. This validates the bundled pilot runtime, live controls and
reporting; it does not establish a full-city portable build or a timing speedup.

Validation evidence is recorded in [OVERNIGHT_PROGRESS.md](OVERNIGHT_PROGRESS.md).
Before calling a new build ready, run its own interpreter and live smoke check,
verify its manifest, and inspect a rendered city view from that folder. Repository
tests alone do not validate the bundled runtime.
