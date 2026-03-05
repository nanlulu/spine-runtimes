#!/usr/bin/env python3
"""
Visualize Assassin atlas regions on heroes.png.

Produces assassin_regions.png with:
- Transparent background (only Assassin region pixels are visible)
- Red bounding boxes around each region
- Body-part labels above each box
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from extract_skin import parse_atlas

SKIN_PREFIX = "Assassin/"
LABEL_PREFIX = "Assassin/Assassin_"


def main():
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir.parent / "assets"
    atlas_path = assets_dir / "heroes.atlas"
    png_path = assets_dir / "heroes.png"
    output_path = script_dir / "assassin_regions.png"

    # Parse atlas and filter to Assassin regions
    _, regions = parse_atlas(str(atlas_path))
    assassin_regions = {
        name: r for name, r in regions.items() if name.startswith(SKIN_PREFIX)
    }
    print(f"Found {len(assassin_regions)} Assassin regions")

    # Load source image
    source = Image.open(png_path).convert("RGBA")

    # Create transparent canvas
    canvas = Image.new("RGBA", source.size, (0, 0, 0, 0))

    # Copy each Assassin region from source to canvas
    for name, r in assassin_regions.items():
        # Atlas bounds stores original (pre-rotation) dims; for rotate=90
        # the physical pixel rectangle has width/height swapped.
        phys_w = r.height if r.rotate == 90 else r.width
        phys_h = r.width if r.rotate == 90 else r.height
        box = (r.x, r.y, r.x + phys_w, r.y + phys_h)
        crop = source.crop(box)
        canvas.paste(crop, (r.x, r.y))

    # Draw bounding boxes and labels
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except (OSError, IOError):
        font = ImageFont.load_default()

    for name, r in assassin_regions.items():
        phys_w = r.height if r.rotate == 90 else r.width
        phys_h = r.width if r.rotate == 90 else r.height
        box = (r.x, r.y, r.x + phys_w - 1, r.y + phys_h - 1)
        draw.rectangle(box, outline="red", width=3)

        # Short label: strip "Assassin/Assassin_" prefix
        if name.startswith(LABEL_PREFIX):
            label = name[len(LABEL_PREFIX):]
        else:
            label = name[len(SKIN_PREFIX):]

        # Draw label with white background for readability
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        text_x = r.x
        text_y = r.y - phys_h - 4
        if text_y < 0:
            text_y = r.y + 2

        draw.rectangle(
            (text_x - 1, text_y - 1, text_x + text_w + 1, text_y + text_h + 1),
            fill="white",
        )
        draw.text((text_x, text_y), label, fill="red", font=font)

    canvas.save(str(output_path))
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
