#!/usr/bin/env python3
"""
Extract a single skin from the shared heroes skeleton into standalone Spine files.

Produces {skin}.json, {skin}.png, {skin}.atlas, and viewer.html that any Spine
runtime can load independently.

Usage:
    python extract_skin.py --skin Assassin --output-dir ./assassin/
    python extract_skin.py --list-skins
"""

import argparse
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

# ---------------------------------------------------------------------------
# Atlas data structures (extended from generate_skin.py)
# ---------------------------------------------------------------------------

@dataclass
class AtlasPage:
    name: str
    width: int = 0
    height: int = 0
    pma: bool = False
    filter: str = "Linear,Linear"
    scale: float = 1.0


@dataclass
class AtlasRegion:
    name: str
    page: AtlasPage
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    offset_x: int = 0
    offset_y: int = 0
    original_width: int = 0
    original_height: int = 0
    rotate: int = 0  # degrees (0 or 90)
    has_offsets: bool = False

    @property
    def logical_width(self) -> int:
        return self.height if self.rotate == 90 else self.width

    @property
    def logical_height(self) -> int:
        return self.width if self.rotate == 90 else self.height


# ---------------------------------------------------------------------------
# Atlas parser (from generate_skin.py, extended with filter/scale)
# ---------------------------------------------------------------------------

def parse_atlas(atlas_path: str) -> tuple[list[AtlasPage], dict[str, AtlasRegion]]:
    """Parse a Spine atlas file and return pages and a dict of regions keyed by name."""
    with open(atlas_path) as f:
        lines = f.read().splitlines()

    pages: list[AtlasPage] = []
    regions: dict[str, AtlasRegion] = {}
    page: Optional[AtlasPage] = None
    i = 0

    while i < len(lines) and lines[i].strip() == "":
        i += 1

    while i < len(lines):
        line = lines[i]

        if line.strip() == "":
            page = None
            i += 1
            continue

        if page is None:
            page = AtlasPage(name=line.strip())
            i += 1
            while i < len(lines):
                pline = lines[i]
                if ":" not in pline:
                    break
                key, _, val = pline.partition(":")
                key = key.strip()
                val = val.strip()
                if key == "size":
                    parts = val.split(",")
                    page.width = int(parts[0])
                    page.height = int(parts[1])
                elif key == "pma":
                    page.pma = val == "true"
                elif key == "filter":
                    page.filter = val
                elif key == "scale":
                    page.scale = float(val)
                i += 1
            pages.append(page)
            continue

        if ":" in line:
            i += 1
            continue

        region_name = line.strip()
        region = AtlasRegion(name=region_name, page=page)
        i += 1

        while i < len(lines):
            rline = lines[i]
            if ":" not in rline:
                break
            key, _, val = rline.partition(":")
            key = key.strip()
            val = val.strip()

            if key == "bounds":
                parts = val.split(",")
                region.x = int(parts[0])
                region.y = int(parts[1])
                region.width = int(parts[2])
                region.height = int(parts[3])
            elif key == "offsets":
                parts = val.split(",")
                region.offset_x = int(parts[0])
                region.offset_y = int(parts[1])
                region.original_width = int(parts[2])
                region.original_height = int(parts[3])
                region.has_offsets = True
            elif key == "rotate":
                if val == "true":
                    region.rotate = 90
                elif val == "false":
                    region.rotate = 0
                elif val == "90":
                    region.rotate = 90
                else:
                    region.rotate = int(val)
            i += 1

        if not region.has_offsets:
            region.original_width = region.width
            region.original_height = region.height

        if region_name not in regions:
            regions[region_name] = region

    return pages, regions


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def extract_skeleton_json(
    demos_json_path: str,
    target_skin: str,
) -> dict:
    """Extract a standalone skeleton JSON with only default + target skin."""
    with open(demos_json_path) as f:
        data = json.load(f)

    heroes = data["heroes"]

    skins = heroes["skins"]
    default_skin = next((s for s in skins if s["name"] == "default"), None)
    target = next((s for s in skins if s["name"] == target_skin), None)

    if target is None:
        available = [s["name"] for s in skins if s["name"] != "default"]
        print(f"Error: Skin '{target_skin}' not found.")
        print(f"Available skins: {', '.join(sorted(available))}")
        sys.exit(1)

    kept_skins = []
    if default_skin:
        kept_skins.append(default_skin)
    kept_skins.append(target)

    result = {}
    for key in ("skeleton", "bones", "slots", "events", "animations"):
        if key in heroes:
            result[key] = heroes[key]
    result["skins"] = kept_skins

    # Inject A-pose animation
    result["animations"]["a-pose"] = _make_a_pose_animation()

    return result


def _make_a_pose_animation() -> dict:
    """Create an A-pose animation: arms at ~30 deg below horizontal, legs slightly spread, all straight."""
    # Rotation values are deltas relative to the bone's setup pose rotation.
    # Arms: straighten lower arms/hands, position upper arms at ~30 deg below horizontal.
    # Legs: straighten and spread slightly, feet flat.
    return {
        "bones": {
            "arm_upper_far":  {"rotate": [{"value": 44.17}]},
            "arm_lower_far":  {"rotate": [{"value": -97.62}]},
            "hand_far":       {"rotate": [{"value": 0.90}]},
            "arm_upper_near": {"rotate": [{"value": -1.63}]},
            "arm_lower_near": {"rotate": [{"value": -90.73}]},
            "hand_near":      {"rotate": [{"value": -1.35}]},
            "leg_upper_far":  {"rotate": [{"value": -21.99}]},
            "leg_lower_far":  {"rotate": [{"value": 38.21}]},
            "foot_far":       {"rotate": [{"value": 9.18}]},
            "leg_upper_near": {"rotate": [{"value": 2.86}]},
            "leg_lower_near": {"rotate": [{"value": 3.60}]},
            "foot_near":      {"rotate": [{"value": 14.12}]},
        }
    }


# ---------------------------------------------------------------------------
# Region collection from JSON attachment names
# ---------------------------------------------------------------------------

def collect_regions_for_skin(
    skeleton_json: dict,
    atlas_regions: dict[str, AtlasRegion],
) -> dict[str, AtlasRegion]:
    """Collect all atlas regions referenced by attachments in the skeleton JSON."""
    needed_names: set[str] = set()

    for skin in skeleton_json["skins"]:
        for slot_name, attachments in skin.get("attachments", {}).items():
            for att_name, att_data in attachments.items():
                region_name = att_data.get("name", att_name)
                needed_names.add(region_name)

    result: dict[str, AtlasRegion] = {}
    missing: list[str] = []

    for name in sorted(needed_names):
        if name in atlas_regions:
            result[name] = atlas_regions[name]
        else:
            missing.append(name)

    if missing:
        print(f"Warning: {len(missing)} attachment(s) not found in atlas:")
        for m in missing:
            print(f"  {m}")

    return result


# ---------------------------------------------------------------------------
# Shelf packing
# ---------------------------------------------------------------------------

@dataclass
class PackedRegion:
    region: AtlasRegion
    x: int = 0
    y: int = 0


def next_power_of_2(n: int) -> int:
    if n <= 0:
        return 1
    return 1 << (n - 1).bit_length()


def _phys_dims(r: AtlasRegion) -> tuple[int, int]:
    """Return (physical_width, physical_height) in the atlas image."""
    if r.rotate == 90:
        return r.height, r.width
    return r.width, r.height


def shelf_pack(regions: dict[str, AtlasRegion], padding: int = 2) -> tuple[list[PackedRegion], int, int]:
    """Pack regions into a texture using shelf packing. Returns packed list and dimensions."""
    # Sort and pack by physical dimensions (rotated regions have w/h swapped)
    items = sorted(regions.items(), key=lambda kv: _phys_dims(kv[1])[1], reverse=True)

    total_area = sum(_phys_dims(r)[0] * _phys_dims(r)[1] for _, r in items)
    est_side = int(math.ceil(math.sqrt(total_area)))
    canvas_w = next_power_of_2(est_side)

    packed: list[PackedRegion] = []
    shelf_x = padding
    shelf_y = padding
    shelf_h = 0

    for name, region in items:
        pw, ph = _phys_dims(region)
        w = pw + padding
        h = ph + padding

        if shelf_x + w > canvas_w:
            shelf_y += shelf_h
            shelf_x = padding
            shelf_h = 0

        pr = PackedRegion(region=region, x=shelf_x, y=shelf_y)
        packed.append(pr)
        shelf_x += w
        shelf_h = max(shelf_h, h)

    canvas_h = next_power_of_2(shelf_y + shelf_h + padding)

    # If everything doesn't fit, try wider canvas
    if canvas_h > canvas_w * 2:
        canvas_w *= 2
        return shelf_pack(regions, padding)

    return packed, canvas_w, canvas_h


# ---------------------------------------------------------------------------
# PNG repacking
# ---------------------------------------------------------------------------

def repack_png(
    source_png_path: str,
    packed_regions: list[PackedRegion],
    canvas_w: int,
    canvas_h: int,
    output_path: str,
):
    """Crop regions from source PNG and paste into new packed PNG."""
    source = Image.open(source_png_path).convert("RGBA")
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    for pr in packed_regions:
        r = pr.region
        pw, ph = _phys_dims(r)
        crop = source.crop((r.x, r.y, r.x + pw, r.y + ph))
        canvas.paste(crop, (pr.x, pr.y))

    canvas.save(output_path)


# ---------------------------------------------------------------------------
# Atlas writer
# ---------------------------------------------------------------------------

def write_atlas(
    packed_regions: list[PackedRegion],
    canvas_w: int,
    canvas_h: int,
    png_filename: str,
    source_page: AtlasPage,
    output_path: str,
):
    """Write a new Spine atlas file for the packed regions."""
    lines: list[str] = []

    # Page header
    lines.append(png_filename)
    lines.append(f"size:{canvas_w},{canvas_h}")
    lines.append(f"filter:{source_page.filter}")
    if source_page.pma:
        lines.append("pma:true")
    if source_page.scale != 1.0:
        lines.append(f"scale:{source_page.scale}")

    # Region entries
    for pr in packed_regions:
        r = pr.region
        lines.append(r.name)
        lines.append(f"  bounds:{pr.x},{pr.y},{r.width},{r.height}")
        if r.has_offsets:
            lines.append(f"  offsets:{r.offset_x},{r.offset_y},{r.original_width},{r.original_height}")
        if r.rotate == 90:
            lines.append("  rotate:90")

    # Trailing newline
    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_output(output_dir: str, skin_name_lower: str, skeleton_json: dict):
    """Run automated checks on the extracted output."""
    errors: list[str] = []

    json_path = os.path.join(output_dir, f"{skin_name_lower}.json")
    png_path = os.path.join(output_dir, f"{skin_name_lower}.png")
    atlas_path = os.path.join(output_dir, f"{skin_name_lower}.atlas")

    # Check files exist
    for p in (json_path, png_path, atlas_path):
        if not os.path.exists(p):
            errors.append(f"Missing file: {p}")

    if errors:
        return errors

    # Check JSON has required keys
    for key in ("skeleton", "bones", "slots", "skins", "animations"):
        if key not in skeleton_json:
            errors.append(f"JSON missing required key: {key}")

    # Parse the output atlas
    pages, atlas_regions = parse_atlas(atlas_path)
    if not pages:
        errors.append("Atlas has no pages")
        return errors

    # Check every attachment name has a matching atlas region
    for skin in skeleton_json["skins"]:
        for slot_name, attachments in skin.get("attachments", {}).items():
            for att_name, att_data in attachments.items():
                region_name = att_data.get("name", att_name)
                if region_name not in atlas_regions:
                    errors.append(
                        f"Attachment '{region_name}' (skin={skin['name']}, "
                        f"slot={slot_name}) not in atlas"
                    )

    # Check PNG dimensions match atlas page size
    page = pages[0]
    img = Image.open(png_path)
    if img.width != page.width or img.height != page.height:
        errors.append(
            f"PNG size {img.width}x{img.height} != atlas page size "
            f"{page.width}x{page.height}"
        )

    # Check all region bounds fit within PNG (use physical dimensions)
    for name, region in atlas_regions.items():
        pw, ph = _phys_dims(region)
        if region.x + pw > page.width:
            errors.append(f"Region '{name}' exceeds page width")
        if region.y + ph > page.height:
            errors.append(f"Region '{name}' exceeds page height")

    return errors


# ---------------------------------------------------------------------------
# Viewer HTML generator
# ---------------------------------------------------------------------------

def generate_viewer_html(output_dir: str, skin_name: str, skin_name_lower: str, skeleton_json: dict):
    """Generate a standalone viewer.html for the extracted skin."""
    script_dir = Path(__file__).resolve().parent
    dist_js = (script_dir / ".." / ".." / "dist" / "iife" / "spine-webgl.js").resolve()
    shutil.copy2(str(dist_js), os.path.join(output_dir, "spine-webgl.js"))

    # Extract animation names from skeleton JSON
    animations = list(skeleton_json.get("animations", {}).keys())
    default_anim = "idle" if "idle" in animations else (animations[0] if animations else "")

    # Build option tags for the dropdown
    options_html = ""
    for anim in animations:
        selected = ' selected' if anim == default_anim else ''
        options_html += f'<option value="{anim}"{selected}>{anim}</option>\n'

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{skin_name} - Extracted Skin Viewer</title>
<style>
body {{
    margin: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: #ebeef4;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
canvas {{
    width: 640px;
    height: 480px;
    border: 1px solid #ccc;
}}
.controls {{
    margin-top: 12px;
    display: flex;
    align-items: center;
    gap: 10px;
}}
select, label {{
    font-size: 14px;
}}
select {{
    padding: 6px 10px;
    border: 1px solid #999;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
}}
label {{
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
}}
</style>
<script src="spine-webgl.js"></script>
</head>
<body>

<canvas id="canvas" width="640" height="480"></canvas>
<div class="controls">
    <select id="animation-select">
{options_html}    </select>
    <label><input type="checkbox" id="loop-checkbox" checked> Loop</label>
</div>

<script>
(function () {{
    var canvas = document.getElementById("canvas");
    var animSelect = document.getElementById("animation-select");
    var loopCheckbox = document.getElementById("loop-checkbox");
    var gl, renderer, assetManager, skeleton, state;
    var timeKeeper = new spine.TimeKeeper();
    var bgColor = new spine.Color(235 / 255, 239 / 255, 244 / 255, 1);
    var offset = new spine.Vector2();
    var bounds = new spine.Vector2();

    var context = new spine.ManagedWebGLRenderingContext(canvas, {{ alpha: false }});
    gl = context.gl;
    renderer = new spine.SceneRenderer(canvas, gl);
    assetManager = new spine.AssetManager(gl, "", new spine.Downloader());
    assetManager.loadTextureAtlas("{skin_name_lower}.atlas");
    assetManager.loadJson("{skin_name_lower}.json");

    var loaded = false;

    function updateBounds() {{
        skeleton.setToSetupPose();
        skeleton.updateWorldTransform(spine.Physics.update);
        skeleton.getBounds(offset, bounds, []);
    }}

    function playSelected() {{
        if (!state) return;
        var animName = animSelect.value;
        var loop = loopCheckbox.checked;
        state.setAnimation(0, animName, loop);
    }}

    function loadingComplete() {{
        var atlasLoader = new spine.AtlasAttachmentLoader(assetManager.get("{skin_name_lower}.atlas"));
        var skeletonJson = new spine.SkeletonJson(atlasLoader);
        var skeletonData = skeletonJson.readSkeletonData(assetManager.get("{skin_name_lower}.json"));
        skeleton = new spine.Skeleton(skeletonData);
        skeleton.setSkinByName("{skin_name}");
        skeleton.setSlotsToSetupPose();
        var stateData = new spine.AnimationStateData(skeleton.data);
        stateData.defaultMix = 0.2;
        state = new spine.AnimationState(stateData);
        updateBounds();
        playSelected();
        state.apply(skeleton);
        skeleton.updateWorldTransform(spine.Physics.update);
    }}

    animSelect.addEventListener("change", playSelected);
    loopCheckbox.addEventListener("change", playSelected);

    var loadingScreen = new spine.LoadingScreen(renderer);

    function loop() {{
        requestAnimationFrame(loop);
        timeKeeper.update();

        var complete = assetManager.isLoadingComplete();
        if (complete) {{
            if (!loaded) {{
                loaded = true;
                loadingComplete();
            }}

            renderer.camera.position.x = offset.x + bounds.x / 2;
            renderer.camera.position.y = offset.y + bounds.y / 2;
            renderer.camera.viewportWidth = bounds.x * 1.4;
            renderer.camera.viewportHeight = bounds.y * 1.4;
            renderer.resize(spine.ResizeMode.Fit);

            gl.clearColor(bgColor.r, bgColor.g, bgColor.b, bgColor.a);
            gl.clear(gl.COLOR_BUFFER_BIT);

            state.update(timeKeeper.delta);
            state.apply(skeleton);
            skeleton.updateWorldTransform(spine.Physics.update);

            renderer.begin();
            renderer.drawSkeleton(skeleton, true);
            renderer.end();
        }}
        loadingScreen.draw(complete);
    }}

    requestAnimationFrame(loop);
}})();
</script>

</body>
</html>
"""
    viewer_path = os.path.join(output_dir, "viewer.html")
    with open(viewer_path, "w") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Main extraction pipeline
# ---------------------------------------------------------------------------

def list_skins(demos_json_path: str):
    """List all available skins in the skeleton JSON."""
    with open(demos_json_path) as f:
        data = json.load(f)
    skins = data["heroes"]["skins"]
    print("Available skins:")
    for s in skins:
        if s["name"] == "default":
            continue
        att_count = sum(len(v) for v in s.get("attachments", {}).values())
        print(f"  {s['name']} ({att_count} attachments)")


def extract_skin(
    skin_name: str,
    output_dir: str,
    demos_json_path: str,
    atlas_path: str,
    png_path: str,
):
    """Full extraction pipeline."""
    skin_name_lower = skin_name.lower()
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Parse atlas
    print(f"Parsing atlas: {atlas_path}")
    pages, atlas_regions = parse_atlas(atlas_path)
    source_page = pages[0]
    print(f"  Found {len(atlas_regions)} unique regions across {len(pages)} page(s)")

    # Step 2: Extract skeleton JSON
    print(f"Extracting skeleton JSON for skin '{skin_name}'...")
    skeleton_json = extract_skeleton_json(demos_json_path, skin_name)
    skin_count = len(skeleton_json["skins"])
    print(f"  Kept {skin_count} skin(s): {[s['name'] for s in skeleton_json['skins']]}")

    # Step 3: Collect needed regions
    print("Collecting atlas regions from attachment names...")
    needed_regions = collect_regions_for_skin(skeleton_json, atlas_regions)
    print(f"  Found {len(needed_regions)} regions to extract")

    # Step 4: Shelf pack
    print("Packing regions...")
    packed, canvas_w, canvas_h = shelf_pack(needed_regions)
    print(f"  Packed into {canvas_w}x{canvas_h}")

    # Step 5: Repack PNG
    out_png = os.path.join(output_dir, f"{skin_name_lower}.png")
    print(f"Repacking PNG -> {out_png}")
    repack_png(png_path, packed, canvas_w, canvas_h, out_png)

    # Step 6: Write atlas
    out_atlas = os.path.join(output_dir, f"{skin_name_lower}.atlas")
    print(f"Writing atlas -> {out_atlas}")
    write_atlas(packed, canvas_w, canvas_h, f"{skin_name_lower}.png", source_page, out_atlas)

    # Step 7: Write JSON
    out_json = os.path.join(output_dir, f"{skin_name_lower}.json")
    print(f"Writing JSON -> {out_json}")
    with open(out_json, "w") as f:
        json.dump(skeleton_json, f, separators=(",", ":"))

    # Step 8: Generate viewer
    print("Generating viewer.html")
    generate_viewer_html(output_dir, skin_name, skin_name_lower, skeleton_json)

    # Step 9: Verify
    print("\nVerifying output...")
    errors = verify_output(output_dir, skin_name_lower, skeleton_json)
    if errors:
        print(f"  FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"    - {e}")
        return False
    else:
        print("  All checks passed!")

    # Summary
    json_size = os.path.getsize(out_json)
    png_size = os.path.getsize(out_png)
    atlas_size = os.path.getsize(out_atlas)
    print(f"\nOutput files in {output_dir}:")
    print(f"  {skin_name_lower}.json  ({json_size:,} bytes)")
    print(f"  {skin_name_lower}.png   ({canvas_w}x{canvas_h}, {png_size:,} bytes)")
    print(f"  {skin_name_lower}.atlas ({atlas_size:,} bytes)")
    print(f"  viewer.html")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract a single skin into standalone Spine files"
    )
    parser.add_argument(
        "--skin", type=str, default=None,
        help="Skin name to extract (e.g., Assassin)"
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory (default: ./{skin_lower}/)"
    )
    parser.add_argument(
        "--list-skins", action="store_true",
        help="List all available skins and exit"
    )

    script_dir = Path(__file__).resolve().parent
    default_assets = script_dir.parent / "assets"
    parser.add_argument(
        "--json", type=str,
        default=str(default_assets / "demos.json"),
        help="Path to demos.json"
    )
    parser.add_argument(
        "--atlas", type=str,
        default=str(default_assets / "heroes.atlas"),
        help="Path to heroes.atlas"
    )
    parser.add_argument(
        "--png", type=str,
        default=str(default_assets / "heroes.png"),
        help="Path to heroes.png"
    )

    args = parser.parse_args()

    if args.list_skins:
        list_skins(args.json)
        return

    if not args.skin:
        parser.error("--skin is required (or use --list-skins)")

    output_dir = args.output_dir or f"./{args.skin.lower()}/"

    success = extract_skin(
        skin_name=args.skin,
        output_dir=output_dir,
        demos_json_path=args.json,
        atlas_path=args.atlas,
        png_path=args.png,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
