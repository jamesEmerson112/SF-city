# San Francisco geography import

The importer downloads the complete official street and building datasets, keeps
the original GeoJSON in a local cache, and writes a citywide map plus nearby-detail
tiles. This is an authentic geographic baseline. It does not establish current
building uses, a complete sidewalk network, or a population model.

## Reproduce the import

From the repository root on Windows:

```powershell
venv/Scripts/python.exe scripts/fetch_sf_geography.py
```

The default raw cache is `.cache/sf-geography/`; the normalized manifest is
`.local/civic/geography/sf-geography.json`. Both locations are local generated
data. The source code and offline tests are small enough for the repository.

```powershell
# Verify cached pages and rebuild without any network access.
venv/Scripts/python.exe scripts/fetch_sf_geography.py --offline

# Fetch a fresh source snapshot, preserving raw provenance and checksums.
venv/Scripts/python.exe scripts/fetch_sf_geography.py --refresh

# Download first and normalize separately.
venv/Scripts/python.exe scripts/fetch_sf_geography.py --download-only
```

`--cache-dir`, `--output-dir`, `--page-size` and `--tile-size` customize the paths
and batching. Offline mode requires a complete cache for the same page-size/query
configuration. No account, API token, or application secret is required. Public
requests retry transient failures; incomplete pages are written atomically and
can be reused when the source version has not changed. The importer checks source
update timestamps before and after pagination and refuses mixed source versions.

## Official sources and dates

| Layer | Official source | Observation and interpretation |
|---|---|---|
| Streets | [Streets – Active and Retired, 3psu-pn9h](https://data.sfgov.org/d/3psu-pn9h) | Public Works basemap. The inspected source has 17,170 total records and 16,373 active records; import queries `active = true`. Source records report `data_as_of=2026-09-05T03:55:00`; the source field does not state a timezone. |
| Buildings | [Building Footprints, ynuv-fyni](https://data.sfgov.org/d/ynuv-fyni) | 177,023 source footprints derived from a 2010 Pictometry building model, with later splitting/refinement described in the attached May 2017 methodology. Source records report `data_as_of=2023-09-11T12:00:00`; recent portal refreshes are not new building measurements. |
| Land | [SF Shoreline and Islands, txuc-3kzm](https://data.sfgov.org/d/txuc-3kzm) | Historical mainland shoreline, southern county line, and islands. Source data was last updated July 12, 2016; metadata was updated March 13, 2024. The old `rgcx-5tix` map is a presentation layer whose direct API returned null geometry; the importer uses the actual replacement dataset. |

All three inspected datasets declare the **Open Data Commons Public Domain
Dedication and License (PDDL)**. The importer verifies the source's `licenseId`
and preserves its actual license name/link and City and County of San Francisco
attribution. See the [PDDL terms](https://opendatacommons.org/licenses/pddl/1-0/).

Every source manifest records its dataset URL, exact paginated query URLs,
retrieval timestamp, source update timestamp, metadata checksum, individual page
checksums, row count, license, and observation caveat. Original WGS84 coordinates
remain in the cached GeoJSON; normalized records retain source building IDs,
street CNNs, parcel identifiers and source-system dates.

The checked snapshot was retrieved on September 6, 2026, from 07:22 to 07:24 UTC.
Its normalized manifest checksum is
`ed92723159a36f303e19e55dafe7b0c8cc2833c3298b40a093556fffedcdb117`.

## Coordinates and vertical measurements

The shared origin is longitude **-122.4193**, latitude **37.7793**, near City Hall
and matching the original visual-study origin. Coordinates are `[east,north,up]`
in meters. Godot converts these into its own axis convention at the display
boundary.

`civic_center.geography.LocalProjection` converts WGS84 longitude/latitude at
ellipsoid height zero to ECEF, subtracts origin ECEF, and rotates the difference
into local east and north components. Its inverse solves those same horizontal
equations. Tests cover the origin, one-meter displacements, mainland edges,
islands, and coordinates near the Farallones. Normalized positions are rounded
to 0.001 m; this precision is not a claim of millimeter source accuracy.

Geometry initially has local `up=0`. The horizontal transform does not silently
turn earth curvature into terrain. Terrain integration supplies the vertical
surface separately. Source vertical measurements remain explicit:

| Output | Source field | Meaning |
|---|---|---|
| `height_m` | `hgt_median_m` | LiDAR-derived median height above ground. A box extrusion using this value does not reproduce roof shape or the exact highest point. |
| `ground_elevation_navd88_m` | `gnd_min_m` | Zonal minimum ground elevation in NAVD 1988 meters. This is elevation, not building height. |
| `roof_peak_elevation_navd88_m` | `peak_1st_m` | Highest first-return grid cell in NAVD 1988 meters; distinct from a surveyed roof peak. |

One imported building part lacks a positive median height and receives an
explicitly labeled 6 m estimate. No use, dwelling count, household, job, or
capacity is inferred by the geography importer. Pictometry's `p2010_name` often
contains a model filename; it is retained as a source name, not presented as a
verified real-world building name.

City Hall's source ID is `201006.0000041`, normalized as
`sf-building:201006.0000041`, parcel `SF0787001`. Its centroid is
`[6.349,-2.634,0]`; its footprint bounds are east `[-46.008,58.977]`, north
`[-71.661,66.484]`, approximately 104.985 by 138.145 m. Its ground minimum is
17.61 m NAVD88, median height 26.41 m, and highest first return 105.82 m NAVD88.
These fields support aligning the separately authored landmark without altering
the original Blender source asset.

## Street topology and coverage limits

Street curves retain every normalized bend vertex. Graph edges connect successive
vertices; street endpoints join through official CNN node IDs. An arbitrary
geometric crossing does not create an intersection. Null, zero and negative node
IDs never merge unrelated endpoints.

The source audit found 18 CNN node IDs whose recorded endpoint locations
disagreed, in one case by 1,658.906 m. Joining each such ID unconditionally produced
false long jumps and five collapsed edges. The importer partitions inconsistent
IDs into deterministic coordinate groups with maximum pairwise separation of
2 m. The resulting maximum actual snap is 1.191 m. Source CNN IDs, source layers,
conflict flags and grouping statistics remain in the graph. Grade/level is not
available in this source. The final graph is validated by the same `WalkingGraph`
used by the simulation, including its positive-edge-length checks.

Retired streets are excluded by the source query. Paper and pseudo streets are
excluded from the displayed physical network. Freeways, ramps and private layers
remain available for display but are excluded from the walking graph. Walking
edges are bidirectional proxies; motor-traffic one-way fields remain separate.
Legal pedestrian access, sidewalks, crossings and curb ramps are not established
by this dataset. Rendered road widths are labeled estimates based on class code.

The map includes the mainland and source islands. Initial camera bounds follow
the available urban street/building coverage: approximately east
`[-8308.899,5435.381]`, north `[-8274.498,5864.988]` m. `land_bounds` separately
preserves outlying land, including Farallon polygons roughly 60 km west of the
origin; the full land extent is east `[-60727.251,8071.009]`, north
`[-9389.772,16698.740]` m. No street or building records occur in the Farallon
extent in this source snapshot. A whole-city source download is not a claim to
model every feature throughout San Francisco's maritime legal jurisdiction.

The building source explicitly includes selected adjacent-county parcels.
`centroid_on_source_land` and `source_land_polygon_id` report containment in the
historical shoreline polygons, including their holes. Containment uses the
normalized shoreline simplified with 2 m tolerance. A point outside that mask
may represent a nearby-county parcel, a pier, or a shoreline-vintage mismatch;
the flag is not a legal jurisdiction classification. Cohort generation can use
the flag conservatively while retaining all imported geometry for inspection.
Of the 3,273 outside-mask centroids, 3,057 lie south of the mainland polygon's
southernmost northing (-7,900.515 m); the remaining 216 require more specific
shoreline or parcel inspection. This is a geometric audit, not an assignment
of municipal jurisdiction.

## Output and validation

The manifest provides `graph_path`, `building_index_path`, spatial `tiles`, land
polygons, simplified overview streets, source manifests, statistics, bounds and
checksums. Paths are relative to the manifest directory. `files[path]` is the
SHA-256 of the exact file bytes. The manifest's own checksum is canonical JSON
with sorted keys and compact separators, excluding its own `sha256` field.

Building parts live in 500 m centroid tiles whose culling bounds include each
complete footprint. Multipolygon parts have distinct IDs while retaining a shared
source building ID. Street parts appear in each intersected bounding-box tile.
Courtyard holes remain in `rings`; `footprint` is the outer ring. A renderer must
triangulate the holes correctly or omit the roof for those buildings, rather than
fill courtyards. The source-index checksum and source IDs support reproducible
scenario generation independent of tile rendering.

| Check | Imported snapshot |
|---|---:|
| Active source street records | 16,373 |
| Paper/pseudo records excluded | 462 |
| Physical street parts displayed | 15,911 |
| Display parts excluded from walking graph | 507 |
| Walking graph nodes | 27,452 |
| Walking graph edges | 33,649 |
| Conflicting source node IDs partitioned | 18 |
| Zero-length graph edges after validation | 0 |
| Source building footprints | 177,023 |
| Normalized building polygon parts | 177,140 |
| Parts with courtyard/interior holes | 3,282 |
| Parts with measured median height | 177,139 |
| Parts with estimated height | 1 |
| Building part centroids inside source land | 173,867 |
| Building part centroids outside source land | 3,273 |
| Land polygons | 38 |
| Spatial tiles | 576 |

Detailed land-membership counts are recorded under
`statistics.buildings.centroids_on_source_land`,
`statistics.buildings.centroids_outside_source_land`, and
`statistics.buildings_by_source_land_polygon` in the generated manifest.
The mainland polygon contains 173,209 building part centroids; the combined
Treasure Island/Yerba Buena Island polygon contains 658. The other source land
polygons have no building part centroids in this snapshot. Their land geometry
is preserved, but the download does not establish complete island building detail.

The initial full source download took 122.5 seconds in the development
environment. Raw source pages occupied 163.7 MB, including 155.7 MB of building
GeoJSON. Final offline normalization, including topology validation and shoreline
membership, took 91.8 seconds and produced 389.4 MB of artifacts plus a 4.9 MB
manifest (decimal MB). These are
measured import costs for this checkout, not rendering-performance promises.

```powershell
venv/Scripts/python.exe -m pytest tests/civic_center/test_geography.py -q -o cache_dir=.cache/pytest
```

The offline fixtures cover coordinate scale/roundtrips, CNN clustering, crossing
separation, excluded street types, holes, multipolygon identity, height/elevation
separation, island membership, deterministic tiled output, source pagination,
offline cache checksums, and source license/schema changes.

## Terrain and visual preparation

The optional terrain importer uses the [USGS 3DEP bare-earth elevation service](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer).
It requests floating-point elevations with the `None` raster function, preserves
the original TIFF and catalog responses, and resamples into the same local
WGS84 east/north grid as the street/footprint import. It does not interpret a
hillshade image as height data.

```powershell
venv/Scripts/python.exe -m pip install -r civic_center/requirements-data.txt
venv/Scripts/python.exe scripts/fetch_sf_terrain.py
venv/Scripts/python.exe scripts/build_sf_scenario.py --population 200
venv/Scripts/python.exe scripts/prepare_sf_visuals.py
python -m civic_center --world city --location city
```

The cached `terrain.json` has 1,024-by-1,024 samples, approximately 18–19 meters
apart. Bounds refer to sample centers; rows run north to south. Its rectangle
covers the mainland and Bay islands, with no elevation claim for the Farallon
Islands. Null or out-of-bounds samples remain unknown. Elevations are stored in
the source vertical frame, and local heights subtract 18.458 m at the City Hall
origin. `catalog.json` preserves the intersecting source acquisitions and their
vertical datum fields: 29 records declare NAVD 88 and 12 leave that field empty.
This service export is a multi-resolution mosaic, not a newly surveyed 2026 city.

The runtime uses the same NW–SE terrain triangles for road, resident and camera
height sampling. The bilinear sampler remains available for source raster
preparation. This distinction matters on hills: interpolating only a street
segment's endpoint heights can place a traveler inside the terrain between them.

`prepare_sf_visuals.py` leaves the observed geographic manifest unchanged and
writes a separate `visual-index.json` linked to its source hash. Per-tile files
contain compact oriented boxes for distant building display and explicit roof
triangles for courtyard buildings. The box is a visual approximation, not a
replacement footprint. The current sidecar represents 177,140 building parts
in 18.25 MB and supplies 117,461 triangles for all 3,282 courtyard roofs; every
accepted triangulation preserves the outer-minus-hole area.

## City Hall landmark

The original geographic landmark uses building `sf-building:201006.0000041`'s
observed footprint and 26.41 m median roof height. Its procedural facade and dome
are authored approximations. Total height is 93.726 m, from the City's reported
307 feet 6 inches in its [docent presentation](https://www.sf.gov/sites/default/files/2021-12/12746-DocentPresentation.pdf).
The separate LiDAR peak-minus-minimum-ground statistic is retained in source
metadata; it is not silently treated as the architectural height.

The editable source is `assets/source/city-hall-geographic.blend`, with measured
input/provenance in `assets/source/city-hall-geometry.json`. Prepare the input
with `scripts/prepare_city_hall_landmark.py`, then run
`scripts/build_city_hall_landmark.py` inside Blender. The script creates an
isolated scene, writes its source and GLB, and restores the previous active scene.
Runtime assets and metadata are in `viewer/assets/`; no Blender process is
required to display them.

Three additional original exteriors make the skyline recognizable: Transamerica
Pyramid, Coit Tower and Sutro Tower. Their observed footprint records anchor
position; their special architectural shapes are not recovered from a single
median footprint height. [USGS station 1239's building layout](https://www.strongmotioncenter.org/NCESMD/photos/NSMP/bldlayouts/bld1239.pdf)
provides the pyramid's 853-foot height and 53-meter base. The
[Recreation and Parks brochure](https://sfrecpark.org/DocumentCenter/View/7387/CoitTowerBrochure_V5)
reports Coit Tower at 212 feet; that reference is retained explicitly because
other publications use 210 feet. [Sutro Tower's operator](https://www.sutrotower.com/about)
reports 977 feet. Facade, flute, arch, truss and antenna proportions are original
approximations, not measured current exterior inventories.

`prepare_skyline_landmarks.py` verifies the geographic tile/graph hashes and
records the selected source parts in `assets/source/skyline-geometry.json`.
Run `build_skyline_landmarks.py` inside Blender to export the three GLBs and
`assets/source/sf-skyline-landmarks.blend`. Both landmark builders update the
manifest by ID, preserving other entries. Sutro's three identified overlapping
tower parts map to one exterior; adjacent service buildings remain. Rendered
mesh bounds are checked against the reported total heights. Nearby source street
nodes support walking navigation without claiming surveyed landmark entrances.

## Parcel uses and generated home/work assignments

The optional [San Francisco Land Use](https://data.sfgov.org/d/c5ge-t6pj) source
is published by SF Planning under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
The downloaded snapshot contains 153,765 records with `data_as_of` August 17,
2026. Each row describes a parcel, a parcel group or an analytical geography.
This is a different source and observation date from the older footprint model.

```powershell
venv/Scripts/python.exe scripts/fetch_sf_landuse.py
venv/Scripts/python.exe scripts/fetch_sf_landuse.py --offline
```

The importer downloads public use attributes without property owners or tax
values. It preserves ordinary residential units, special residential units/beds,
and commercial square feet by cultural/institutional/educational, medical,
office, retail, industrial and visitor uses. Special units are kept separate
because the source explains that a unit can mean a bed in group quarters.
Commercial floor area is an allocation weight, not a measured job count.

Footprint `mblr` identifiers join to normalized source `mapblklot` identifiers.
A group with multiple parcels is counted once, even if many footprints match.
Relative footprint area distributes its allocation weight among matched buildings;
the source group totals remain labeled as group totals. No building receives a
claim that it individually contains every unit in the parcel group.

The first full join matched 167,930 of 177,140 footprint parts uniquely, covering
144,666 source records. It found 155,761 footprints on groups with ordinary
residential units and 14,779 on groups with positive commercial area. Another
4,874 footprints were unmatched, 4 had ambiguous joins, and 4,332 carried
identifiers outside the accepted SF parcel-key format. These cases do not become
invented residential or commercial observations. Analytical geometries and parcel
changes between source vintages remain explicit gaps.

`landuse.json` contains the normalized attributes and source-page checksums;
`join-report.json` records the group-preserving QA. The initial normalized file
is about 71.1 MB. The source's totals and matched totals are diagnostics of these
records, not a population estimate. Generated residents and workplace assignments
remain synthetic even when their building eligibility comes from observed uses.

The city generator uses positive ordinary-unit and commercial-area eligibility
when this optional index is installed. It computes group allocation weights
before selecting a spatially distributed cohort. Commercial square feet remain
weights, not calibrated job counts. Generator v4 produces distinct home/work
pairs for all 1,000 residents in the current integration fixture, with walking
commutes between 150 and 3,000 meters. Repeating schedules are generated examples.

```powershell
venv/Scripts/python.exe scripts/prepare_sf_uses.py
python -m civic_center --world city --use-overlay
```

Press `U` to toggle the observed-use overlay. It distinguishes residential,
mixed, institutional, office, retail and other source categories. City Hall keeps
its authored materials. Unknown exact joins stay unclassified. The inspector
labels every shared total as a source-group fact. Compact tile colors occupy
11.44 MB; full inspection records occupy 67.68 MB and load through a bounded
48-tile cache. Both indexes verify the geographic and land-use source hashes.

## Named destinations

```powershell
venv/Scripts/python.exe scripts/fetch_sf_places.py
venv/Scripts/python.exe scripts/fetch_sf_places.py --offline
python -m civic_center --place "Mission"
```

The optional `places-index.json` offers 41 [Analysis Neighborhoods](https://data.sfgov.org/d/j2bu-swwd)
and 253 [Recreation and Parks properties](https://data.sfgov.org/d/gtr9-ntp6)
within San Francisco. Both sources declare PDDL. Analysis areas aggregate Census
tracts for reporting; the City explicitly says they are not an official map of
neighborhood boundaries. Recreation and Parks properties include civic plazas,
gardens, libraries and other holdings, and do not cover every park or all federal
lands. They are not a vegetation or land-cover classification.

The department source has 255 records. Camp Mather in Groveland and Sharp Park
in Pacifica remain outside this SF navigation index. Nine polygon parts had no
target on the geographic source's known land and were omitted; every retained
destination has at least one valid part. Original holes and source properties
are retained in `places-areas.json`. The optional index is approximately 143 KB
and the polygon sidecar 2.22 MB. They leave the geographic manifest unchanged.

Camera targets are verified interior points on known source land, including
concave shapes and polygons with holes. Ground-view targets use the nearest
connected source street node. Such targets are navigation aids, not surveyed
entrances, sidewalk locations or accessibility assessments. Exact IDs and names
take precedence over partial search matches; genuinely ambiguous names require
a specific result. Source observation notes and dates travel with the index.

## Representative daylight

The optional daylight cycle uses the [NOAA general solar-position equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF)
at the City Hall latitude/longitude for a representative September 6 in PDT.
The displayed simulation clock drives the sun direction, and the same reference
day repeats. It is an approximate geometric sun model, without atmospheric
refraction, real weather, seasonal progression or an implied real-world date for
the generated residents. Sky colors, twilight and readable night fill are
artistic presentation choices.

The independent worked [NREL SPA reference](https://docs.nlr.gov/docs/fy08osti/34302.pdf)
is used as a one-degree direction sanity check; this compact NOAA implementation
does not claim SPA precision. Headless tests also cover compass orientation,
day wrapping, invalid inputs, frozen lighting while paused and exact restoration
of the original fixed environment. Use `--lighting fixed` for inspection or
controlled rendering comparisons.

## Selected areas and facade detail

Selecting a named area loads the checksum-verified polygon sidecar and draws only
that source boundary. Amber identifies an analysis area and teal identifies a
Rec/Park property. Each ring closes independently, including holes and separate
polygon parts. The annotation follows the common terrain triangles, skips missing
samples and remains visible through buildings. It is a selection aid, not a
physical fence or a new boundary survey. Returning to City Hall or the city
overview clears it; landmarks do not inherit a previous area selection.

The optional facade treatment adds restrained window/floor rhythm to nearby
extruded walls. Roofs, distant silhouettes and authored landmarks keep their
existing materials. These are illustrative patterns, not surveyed windows,
measured floors or signals of actual occupancy. The observed-use overlay bypasses
the treatment and preserves its category colors. Use `--facades off` or the
Illustrative facades checkbox to compare it with the plain source extrusions.

## Recorded street trees

```powershell
venv/Scripts/python.exe scripts/fetch_sf_trees.py
venv/Scripts/python.exe scripts/fetch_sf_trees.py --offline
python -m civic_center --trees off
```

The optional tree layer uses the replacement [San Francisco Street Tree Inventory](https://data.sfgov.org/d/uzd4-f6yf),
which declares PDDL. Public Works describes it as an extract of its asset system
for street trees, with removed trees and non-tree planting assets excluded.
Individual records can lag field conditions, and coordinates can be absent or
imprecise. It is not a census of all vegetation or all trees in Golden Gate Park,
the Presidio or other parkland.

The [legacy feed](https://data.sfgov.org/d/tkzw-k3nq) explicitly warns about historical
removals and duplicate records and points to this replacement inventory. The
importer uses the new dataset ID and column schema directly. It downloads only
location, species, planting/site attributes, source diameter and source dates;
it does not need addresses, caretakers or permit notes.

The September 6 download contains 144,425 records. Strict normalization excludes
2,123 explicit stump/empty-site species labels, 5,698 records without coordinates
and one point outside the existing source land mask. It retains 136,603 records
in 440 spatial tiles, totaling 67.45 MB. These records occupy 129,833 distinct
horizontal positions: 9,080 source records share 2,310 positions. The normalized
data retains every unique source ID. The viewer uses one deterministic silhouette
per exact coordinate to avoid overlapping copies; it does not randomly move
those records or describe their count as a calibrated tree population.

Most retained source rows carry a July 1, 2026 update date, with later updates
through September 5. This is a source-system row update field, not evidence that
each tree was surveyed on that day. The separate portal upload time is retained.
The source's diameter-at-breast-height field is preserved without invented units;
the downloaded metadata does not specify its units. It does not determine height.

Broadleaf, conifer and palm forms, height, canopy width, trunk thickness and colors
are explicitly illustrative. Species text selects a broad display form, while a
stable ID seed supplies restrained size variation. Source horizontal coordinates
remain fixed; the shared terrain supplies display height, and missing terrain
is omitted. The optional `tree-index.json` checks the geographic identity and
records every tile's checksum. This is a visual layer; it adds no simulated
tree growth, collision, carbon accounting or resource consumption.
