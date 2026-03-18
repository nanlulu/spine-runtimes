#!/usr/bin/env python3
"""
Extract orientation data from the dummy atlas to produce an orientation map.

Reads dummy/dummy.atlas + dummy/dummy.png, extracts each Dummy region,
un-rotates if needed, measures PCA angle and aspect ratio, and writes
dummy/orientation_map.txt for use by rabbit_to_skin.py.

Usage:
    python extract_orientation_map.py
    python extract_orientation_map.py --atlas dummy/dummy.atlas --png dummy/dummy.png --output dummy/orientation_map.txt
"""

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

from generate_skin import parse_atlas


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


def main():
    parser = argparse.ArgumentParser(description="Extract orientation map from dummy atlas")
    parser.add_argument("--atlas", type=str, default="dummy/dummy.atlas")
    parser.add_argument("--png", type=str, default="dummy/dummy.png")
    parser.add_argument("--output", type=str, default="dummy/orientation_map.txt")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    atlas_path = script_dir / args.atlas
    png_path = script_dir / args.png
    output_path = script_dir / args.output

    # Parse atlas
    pages, regions = parse_atlas(str(atlas_path))
    print(f"Parsed {len(regions)} regions from {atlas_path}")

    # Open atlas image
    atlas_img = Image.open(png_path).convert("RGBA")
    print(f"Atlas image: {atlas_img.size}")

    prefix = "Dummy/Dummy_"
    entries = []

    for region_name, region in sorted(regions.items()):
        if not region_name.startswith(prefix):
            continue

        suffix = region_name[len(prefix):]

        # In Spine atlas format, bounds width/height are the LOGICAL (original) dims.
        # When rotate:90, the physical area on the PNG is swapped: phys_w=height, phys_h=width.
        if region.rotate == 90:
            phys_w = region.height
            phys_h = region.width
        else:
            phys_w = region.width
            phys_h = region.height

        crop = atlas_img.crop((region.x, region.y, region.x + phys_w, region.y + phys_h))

        # Un-rotate to get logical orientation
        if region.rotate == 90:
            # Spine atlas rotate:90 means the region was rotated 90° CW for packing
            # To get back to logical orientation, rotate 90° CCW
            crop = crop.transpose(Image.ROTATE_90)

        # Now crop is in logical orientation
        logical_w, logical_h = crop.size
        aspect_ratio = logical_w / logical_h if logical_h > 0 else 1.0
        wider_than_tall = logical_w > logical_h

        # Compute PCA angle
        pca_angle = get_blob_angle(crop)

        entries.append({
            "name": suffix,
            "pca_angle": pca_angle,
            "aspect_ratio": aspect_ratio,
            "wider_than_tall": wider_than_tall,
            "logical_w": logical_w,
            "logical_h": logical_h,
        })

        print(f"  {suffix:30s}  angle={pca_angle:6.1f}  ar={aspect_ratio:.2f}  "
              f"{'W>H' if wider_than_tall else 'H>W'}  {logical_w}x{logical_h}")

    # Write output
    with open(output_path, "w") as f:
        f.write("# Orientation map extracted from dummy atlas\n")
        f.write("# part_name\tpca_angle\taspect_ratio\twider_than_tall\tlogical_w\tlogical_h\n")
        for e in entries:
            f.write(f"{e['name']}\t{e['pca_angle']:.1f}\t{e['aspect_ratio']:.3f}\t"
                    f"{'true' if e['wider_than_tall'] else 'false'}\t"
                    f"{e['logical_w']}\t{e['logical_h']}\n")

    print(f"\nWrote {len(entries)} entries to {output_path}")


if __name__ == "__main__":
    main()
