"""Copy the original comparison asset into the self-contained Godot project."""

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "comparison/shared"
TARGET = ROOT / "viewer/assets"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for original, staged in [("civic-center.glb", "civic-center.glb"),
                              ("scene.json", "visual.json")]:
        shutil.copyfile(SOURCE / original, TARGET / staged)
    manifest = json.loads((SOURCE / "asset-manifest.json").read_text(encoding="utf-8"))
    manifest.update(schema_version=1, authorship="Original generated City Hall architectural study",
                    source_blend="comparison/shared/civic-center.blend",
                    coordinate_system="standard glTF Y-up, meters",
                    geographic_accuracy="stylized approximation, not surveyed geography",
                    external_assets=[])
    manifest["sha256"] = {name: hashlib.sha256((TARGET / name).read_bytes()).hexdigest()
                          for name in ("civic-center.glb", "visual.json")}
    (TARGET / "asset-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {manifest['mesh_objects']} City Hall meshes in {TARGET}")


if __name__ == "__main__":
    main()
