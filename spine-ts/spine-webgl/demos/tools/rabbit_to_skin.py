#!/usr/bin/env python3
"""
Map rabbit.png body parts into the Assassin atlas regions for color-block-rabbit/.

Segments the exploded rabbit character sheet into body parts using connected
components, maps them spatially to atlas region names, then composites a new
assassin.png that works with the existing .json and .atlas files.

Usage:
    python rabbit_to_skin.py
    python rabbit_to_skin.py --input assets/rabbit.png --output color-block-rabbit/assassin.png
    python rabbit_to_skin.py --debug  # saves debug images to debug-rabbit/
"""

import argparse
import math
import os
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from generate_skin import parse_atlas, AtlasRegion


# ---------------------------------------------------------------------------
# Background removal & blob segmentation (reused from panda_to_skin)
# ---------------------------------------------------------------------------

def remove_background(img: Image.Image, tolerance: int = 30) -> Image.Image:
    """Remove background using flood-fill from image borders."""
    arr = np.array(img.convert("RGB"), dtype=np.int16)
    h, w = arr.shape[:2]

    corners = [arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]
    bg_color = np.mean(corners, axis=0).astype(np.int16)

    bg_mask = np.zeros((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)
    queue = deque()

    def is_bg(y, x):
        return np.all(np.abs(arr[y, x] - bg_color) < tolerance)

    for x in range(w):
        for y in [0, h - 1]:
            if is_bg(y, x) and not visited[y, x]:
                visited[y, x] = True
                queue.append((y, x))
                bg_mask[y, x] = True
    for y in range(h):
        for x in [0, w - 1]:
            if is_bg(y, x) and not visited[y, x]:
                visited[y, x] = True
                queue.append((y, x))
                bg_mask[y, x] = True

    while queue:
        cy, cx = queue.popleft()
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                visited[ny, nx] = True
                if is_bg(ny, nx):
                    bg_mask[ny, nx] = True
                    queue.append((ny, nx))

    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr.astype(np.uint8), alpha])
    return Image.fromarray(rgba, "RGBA")


def find_blobs(rgba: Image.Image, min_pixels: int = 100):
    """Find connected component blobs in the alpha channel."""
    arr = np.array(rgba)
    alpha = arr[:, :, 3]
    binary = (alpha > 10).astype(np.uint8)

    labeled, num_features = ndimage.label(binary)

    blobs = []
    for i in range(1, num_features + 1):
        mask = labeled == i
        area = int(mask.sum())
        if area < min_pixels:
            continue

        ys, xs = np.where(mask)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        cy = (y0 + y1) / 2
        cx = (x0 + x1) / 2

        crop_arr = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        local_mask = mask[y0:y1, x0:x1]
        crop_arr[local_mask] = arr[y0:y1, x0:x1][local_mask]
        crop = Image.fromarray(crop_arr, "RGBA")

        blobs.append({
            "label": i,
            "bbox": (y0, y1, x0, x1),
            "center": (cy, cx),
            "area": area,
            "crop": crop,
            "width": x1 - x0,
            "height": y1 - y0,
        })

    return blobs


# ---------------------------------------------------------------------------
# Part orientation correction (improved from panda_to_skin)
# ---------------------------------------------------------------------------

EXPECTED_ORIENTATION = {
    "arm_upper": "horizontal",
    "arm_lower": "horizontal",
    "hand": None,
    "leg_upper": "horizontal",
    "leg_lower": "vertical",
    "foot": None,
    "head": None,
    "torso": None,
    "waist": None,
    "neck": None,
}


def get_blob_angle(img: Image.Image) -> float:
    """Compute the angle of the principal axis of non-transparent pixels."""
    arr = np.array(img)
    alpha = arr[:, :, 3]
    ys, xs = np.where(alpha > 10)

    if len(xs) < 10:
        return 0.0

    cx = xs.mean()
    cy = ys.mean()
    dx = xs - cx
    dy = ys - cy

    cov_xx = (dx * dx).mean()
    cov_yy = (dy * dy).mean()
    cov_xy = (dx * dy).mean()

    angle = 0.5 * math.atan2(2 * cov_xy, cov_xx - cov_yy)
    return math.degrees(angle)


def _crop_tight(img: Image.Image) -> Image.Image:
    """Crop image to tight bounding box of non-transparent pixels."""
    arr = np.array(img)
    alpha = arr[:, :, 3]
    ys, xs = np.where(alpha > 10)
    if len(xs) == 0:
        return img
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    return img.crop((x0, y0, x1, y1))


def orient_part(img: Image.Image, part_name: str) -> Image.Image:
    """Rotate a body part image to match the expected bone-local orientation.

    Includes post-rotation aspect ratio guard to handle PCA ambiguity on
    nearly-square blobs.
    """
    category = None
    for cat in EXPECTED_ORIENTATION:
        if part_name.startswith(cat) or part_name == cat:
            category = cat
            break

    if category is None or EXPECTED_ORIENTATION[category] is None:
        return img

    expected = EXPECTED_ORIENTATION[category]
    current_angle = get_blob_angle(img)

    if expected == "horizontal":
        rotation = -current_angle
    elif expected == "vertical":
        if current_angle > 0:
            rotation = 90 - current_angle
        else:
            rotation = -90 - current_angle

    if abs(rotation) < 5:
        return img

    rotated = img.rotate(rotation, resample=Image.BICUBIC, expand=True)
    cropped = _crop_tight(rotated)

    # Post-rotation aspect ratio guard: verify the result matches expectation
    w, h = cropped.size
    if expected == "horizontal" and h > w:
        # Should be wider than tall but isn't — rotate 90°
        cropped = cropped.rotate(90, resample=Image.BICUBIC, expand=True)
        cropped = _crop_tight(cropped)
    elif expected == "vertical" and w > h:
        # Should be taller than wide but isn't — rotate 90°
        cropped = cropped.rotate(90, resample=Image.BICUBIC, expand=True)
        cropped = _crop_tight(cropped)

    return cropped


# ---------------------------------------------------------------------------
# Spatial body-part assignment for rabbit
# ---------------------------------------------------------------------------

def assign_rabbit_parts(blobs: list[dict], img_width: int = 1024) -> dict[str, Image.Image]:
    """Assign blobs to body part names based on spatial position in A-pose layout.

    The rabbit has 16 distinct parts: head, neck, torso, waist,
    and 6 limb parts per side (arm_upper, arm_lower, hand, leg_upper, leg_lower, foot).
    """
    if not blobs:
        raise ValueError("No blobs found in the image")

    blobs_sorted = sorted(blobs, key=lambda b: b["center"][0])

    for i, b in enumerate(blobs_sorted):
        cy, cx = b["center"]
        print(f"  Blob {i}: center=({cx:.0f},{cy:.0f}) size={b['width']}x{b['height']} area={b['area']}")

    parts = {}
    img_cx = img_width / 2

    # Find head: topmost blob with area > 5000
    head_blob = next(b for b in blobs_sorted if b["area"] > 5000)
    parts["head"] = head_blob["crop"]
    head_bottom = head_blob["bbox"][1]

    # Find neck: small blob near center, below head
    non_head = [b for b in blobs_sorted if b["label"] != head_blob["label"]]
    neck_candidates = [b for b in non_head
                       if b["area"] < 5000
                       and b["center"][0] > head_bottom - 20
                       and b["center"][0] < head_bottom + 100
                       and abs(b["center"][1] - img_cx) < 100]
    neck_label = None
    if neck_candidates:
        neck_blob = min(neck_candidates, key=lambda b: abs(b["center"][1] - img_cx))
        parts["neck"] = neck_blob["crop"]
        neck_label = neck_blob["label"]
        print(f"  Found neck: center=({neck_blob['center'][1]:.0f},{neck_blob['center'][0]:.0f})")

    # Remove head, neck, and small head fragments
    head_margin = 50
    remaining = [
        b for b in blobs_sorted
        if b["label"] != head_blob["label"]
        and b["label"] != neck_label
        and not (b["area"] < 3000 and b["center"][0] < head_bottom + head_margin)
    ]

    # Find torso: largest remaining blob near center
    center_blobs = sorted(remaining, key=lambda b: b["area"], reverse=True)
    torso_blob = center_blobs[0]
    parts["torso"] = torso_blob["crop"]
    remaining = [b for b in remaining if b["label"] != torso_blob["label"]]

    # Find waist: blob near center, below torso
    torso_cy = torso_blob["center"][0]
    torso_bottom = torso_blob["bbox"][1]
    waist_candidates = [b for b in remaining
                        if b["center"][0] > torso_cy
                        and b["center"][0] < torso_bottom + 200
                        and abs(b["center"][1] - img_cx) < 150]
    if waist_candidates:
        waist_blob = min(waist_candidates,
                         key=lambda b: abs(b["center"][1] - img_cx) + abs(b["center"][0] - torso_bottom))
        parts["waist"] = waist_blob["crop"]
        remaining = [b for b in remaining if b["label"] != waist_blob["label"]]
        print(f"  Found waist: center=({waist_blob['center'][1]:.0f},{waist_blob['center'][0]:.0f}) area={waist_blob['area']}")

    # Split remaining into left/right of center
    left_blobs = [b for b in remaining if b["center"][1] < img_cx]
    right_blobs = [b for b in remaining if b["center"][1] >= img_cx]

    def assign_side(side_blobs, side_name):
        """Assign blobs for one side. side_name is 'far' (left) or 'near' (right).

        The rabbit has 6 limb parts per side:
        arm_upper, arm_lower, hand, leg_upper, leg_lower, foot
        """
        sorted_blobs = sorted(side_blobs, key=lambda b: b["center"][0])

        if len(sorted_blobs) < 4:
            print(f"  Warning: only {len(sorted_blobs)} blobs on {side_name} side")

        assignments = [
            f"arm_upper_{side_name}",
            f"arm_lower_{side_name}",
            f"hand_{side_name}",
            f"leg_upper_{side_name}",
            f"leg_lower_{side_name}",
            f"foot_{side_name}",
        ]

        for i, blob in enumerate(sorted_blobs):
            if i < len(assignments):
                parts[assignments[i]] = blob["crop"]
                print(f"  Assigned {assignments[i]}: center=({blob['center'][1]:.0f},{blob['center'][0]:.0f}) "
                      f"size={blob['width']}x{blob['height']}")

    # Left side of image = character's right = "far" side
    # Right side of image = character's left = "near" side
    assign_side(left_blobs, "far")
    assign_side(right_blobs, "near")

    # Flip far foot so feet face opposite directions
    if "foot_far" in parts:
        parts["foot_far"] = parts["foot_far"].transpose(Image.FLIP_LEFT_RIGHT)
        print("  Flipped foot_far horizontally")

    return parts


# ---------------------------------------------------------------------------
# Atlas region → body part mapping
# ---------------------------------------------------------------------------

REGION_TO_PART = {
    "head_1": "head",
    "head_2_injured": "head",
    "torso": "torso",
    "neck": "neck",
    "waist": "waist",
    "arm_upper_near": "arm_upper_near",
    "arm_upper_far": "arm_upper_far",
    "arm_lower_near": "arm_lower_near",
    "arm_lower_far": "arm_lower_far",
    "hand_near_1_fistBack": "hand_near",
    "hand_near_2_fistPalm": "hand_near",
    "hand_far_1_fistBack": "hand_far",
    "hand_far_2_fistPalm": "hand_far",
    "leg_upper_near": "leg_upper_near",
    "leg_upper_far": "leg_upper_far",
    "leg_lower_near_1": "leg_lower_near",
    "leg_lower_near_2": "leg_lower_near",
    "leg_lower_far": "leg_lower_far",
    "foot_near_1": "foot_near",
    "foot_near_2_bent": "foot_near",
    "foot_far_1": "foot_far",
    "foot_far_2_bent": "foot_far",
}


# ---------------------------------------------------------------------------
# Fit image into atlas region (reused from panda_to_skin)
# ---------------------------------------------------------------------------

def fit_to_region(img: Image.Image, region: AtlasRegion) -> Image.Image:
    """Resize img to fit atlas region bounds, apply rotation and PMA."""
    target_w = region.width
    target_h = region.height

    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))

    # Scale to FILL the region (may overflow), then center-crop
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Center-crop to target size
    crop_x = (new_w - target_w) // 2
    crop_y = (new_h - target_h) // 2
    canvas = resized.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

    if region.rotate == 90:
        canvas = canvas.transpose(Image.ROTATE_270)

    if region.page.pma:
        arr = np.array(canvas, dtype=np.float32)
        alpha = arr[:, :, 3:4] / 255.0
        arr[:, :, :3] = arr[:, :, :3] * alpha
        canvas = Image.fromarray(arr.astype(np.uint8), "RGBA")

    return canvas


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Map rabbit.png to Assassin atlas regions")
    parser.add_argument("--input", type=str, default="assets/rabbit.png", help="Input character sheet")
    parser.add_argument("--output", type=str, default="color-block-rabbit/assassin.png", help="Output atlas PNG")
    parser.add_argument("--atlas", type=str, default="color-block-rabbit/assassin.atlas", help="Atlas file")
    parser.add_argument("--tolerance", type=int, default=40, help="Background flood-fill color tolerance")
    parser.add_argument("--debug", action="store_true", help="Save debug images")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    input_path = script_dir / args.input
    output_path = script_dir / args.output
    atlas_path = script_dir / args.atlas

    # Step 1: Load and remove background
    print(f"Loading {input_path}...")
    img = Image.open(input_path)
    print(f"  Size: {img.size}, Mode: {img.mode}")

    print("Removing background...")
    rgba = remove_background(img, tolerance=args.tolerance)

    if args.debug:
        debug_dir = script_dir / "debug-rabbit"
        os.makedirs(debug_dir, exist_ok=True)
        rgba.save(debug_dir / "01_background_removed.png")

    # Step 2: Find blobs
    print("Finding blobs...")
    blobs = find_blobs(rgba, min_pixels=200)
    print(f"  Found {len(blobs)} blobs")

    if args.debug:
        for i, b in enumerate(blobs):
            b["crop"].save(debug_dir / f"02_blob_{i:02d}.png")

    # Step 3: Assign body parts
    print("Assigning body parts...")
    img_width = img.size[0]
    body_parts = assign_rabbit_parts(blobs, img_width=img_width)
    print(f"  Assigned {len(body_parts)} body parts: {sorted(body_parts.keys())}")

    if args.debug:
        for name, crop in body_parts.items():
            crop.save(debug_dir / f"03_part_{name}.png")

    # Step 3b: Orient parts to match bone-local expected orientation
    print("Orienting parts...")
    for name in list(body_parts.keys()):
        original = body_parts[name]
        oriented = orient_part(original, name)
        if oriented is not original:
            print(f"  Rotated {name}: {original.size} -> {oriented.size}")
            body_parts[name] = oriented

    if args.debug:
        for name, crop in body_parts.items():
            crop.save(debug_dir / f"03b_oriented_{name}.png")

    # Step 4: Parse atlas and composite
    print(f"Parsing atlas: {atlas_path}")
    pages, atlas_regions = parse_atlas(str(atlas_path))
    page = pages[0]
    print(f"  Atlas: {page.width}x{page.height}, {len(atlas_regions)} regions")

    skin_prefix = "Assassin/Assassin_"
    skin_regions = {
        name[len(skin_prefix):]: region
        for name, region in atlas_regions.items()
        if name.startswith(skin_prefix)
    }
    print(f"  Assassin regions: {len(skin_regions)}")

    # Step 5: Create output atlas
    canvas = Image.new("RGBA", (page.width, page.height), (0, 0, 0, 0))

    if output_path.exists():
        existing = Image.open(output_path).convert("RGBA")
        canvas = existing.copy()

    mapped = 0
    unmapped = []
    for region_suffix, region in skin_regions.items():
        part_key = REGION_TO_PART.get(region_suffix)
        if part_key is None or part_key not in body_parts:
            unmapped.append(region_suffix)
            continue

        part_img = body_parts[part_key]
        fitted = fit_to_region(part_img, region)

        phys_w = region.height if region.rotate == 90 else region.width
        phys_h = region.width if region.rotate == 90 else region.height

        clear = Image.new("RGBA", (phys_w, phys_h), (0, 0, 0, 0))
        canvas.paste(clear, (region.x, region.y))
        canvas.paste(fitted, (region.x, region.y))
        mapped += 1

        if args.debug:
            fitted.save(debug_dir / f"04_fitted_{region_suffix}.png")

    print(f"\n  Mapped {mapped}/{len(skin_regions)} regions")
    if unmapped:
        print(f"  Unmapped: {unmapped}")

    canvas.save(output_path)
    print(f"\nSaved: {output_path}")
    print("Open color-block-rabbit/viewer.html to see the result!")


if __name__ == "__main__":
    main()
