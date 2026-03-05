#!/usr/bin/env python3
"""
AI-Generated Character Skins for Spine Skins Demo.

Generates artwork for each body part via fal.ai's API (or colored placeholders),
and composites it into heroes.png at the correct atlas region positions.

Usage:
    python generate_skin.py --prompt "cyberpunk robot ninja" --skin Assassin
    python generate_skin.py --prompt "test" --skin Assassin --backend placeholder
    python generate_skin.py --extract --skin Assassin
    python generate_skin.py --restore
    python generate_skin.py --dry-run --skin Assassin
"""

import argparse
import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Atlas data structures
# ---------------------------------------------------------------------------

@dataclass
class AtlasPage:
    name: str
    width: int = 0
    height: int = 0
    pma: bool = False


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

    @property
    def logical_width(self) -> int:
        """Width of the image as authored (before rotation for packing)."""
        return self.height if self.rotate == 90 else self.width

    @property
    def logical_height(self) -> int:
        """Height of the image as authored (before rotation for packing)."""
        return self.width if self.rotate == 90 else self.height


# ---------------------------------------------------------------------------
# Atlas parser
# ---------------------------------------------------------------------------

def parse_atlas(atlas_path: str) -> tuple[list[AtlasPage], dict[str, AtlasRegion]]:
    """Parse a Spine atlas file and return pages and a dict of regions keyed by name."""
    with open(atlas_path) as f:
        lines = f.read().splitlines()

    pages: list[AtlasPage] = []
    regions: dict[str, AtlasRegion] = {}
    page: Optional[AtlasPage] = None
    i = 0

    # Skip leading blank lines
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    while i < len(lines):
        line = lines[i]

        # Blank line → next page
        if line.strip() == "":
            page = None
            i += 1
            continue

        # If no current page, this line is the page name
        if page is None:
            page = AtlasPage(name=line.strip())
            i += 1
            # Read page properties
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
                i += 1
            pages.append(page)
            continue

        # Check if this line is a property (has colon) or a region name
        if ":" in line:
            # Unexpected property outside region — skip
            i += 1
            continue

        # Region name
        region_name = line.strip()
        region = AtlasRegion(name=region_name, page=page)
        i += 1

        # Read region properties
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

        if region.original_width == 0 and region.original_height == 0:
            region.original_width = region.width
            region.original_height = region.height

        # Store first occurrence only (some regions are aliases/shared)
        if region_name not in regions:
            regions[region_name] = region

    return pages, regions


# ---------------------------------------------------------------------------
# Skin region finder (atlas prefix enumeration)
# ---------------------------------------------------------------------------

def get_skin_regions(
    atlas_regions: dict[str, AtlasRegion],
    skin_name: str,
) -> dict[str, AtlasRegion]:
    """Return all atlas regions for a skin by matching the '{SkinName}/' prefix.

    Keys are the region suffix after '{SkinName}/{SkinName}_' (e.g., 'arm_lower_far').
    This avoids the unreliable demos.json path mapping.
    """
    prefix = f"{skin_name}/"
    name_prefix = f"{skin_name}/{skin_name}_"
    result: dict[str, AtlasRegion] = {}

    for region_name, region in atlas_regions.items():
        if region_name.startswith(prefix):
            # Extract the body part suffix: e.g., "arm_lower_far" from
            # "Assassin/Assassin_arm_lower_far"
            if region_name.startswith(name_prefix):
                part_key = region_name[len(name_prefix):]
            else:
                part_key = region_name[len(prefix):]
            result[part_key] = region

    if not result:
        # List available skin prefixes to help the user
        skin_prefixes = sorted({
            name.split("/")[0] for name in atlas_regions if "/" in name
        })
        raise ValueError(
            f"No atlas regions found with prefix '{prefix}'. "
            f"Available skin prefixes: {skin_prefixes}"
        )

    return result


# ---------------------------------------------------------------------------
# Image generation backends
# ---------------------------------------------------------------------------

# Body part prompt templates
PART_PROMPTS: dict[str, str] = {
    "head": "front-facing character head portrait, {style}, centered",
    "torso": "character torso armor/clothing, {style}, front view",
    "arm_upper": "character upper arm, side view, {style}",
    "arm_lower": "character forearm with armor, side view, {style}",
    "hand": "character gloved fist, {style}",
    "leg_upper": "character thigh with armor, side view, {style}",
    "leg_lower": "character shin/lower leg, side view, {style}",
    "foot": "character boot/foot, side view, {style}",
    "waist": "character belt/waist armor, {style}, front view",
    "neck": "character neck piece, {style}",
}


def classify_body_part(part_key: str) -> str:
    """Classify a region suffix like 'arm_lower_far' into a body part category.

    The part_key is the atlas region suffix after '{SkinName}_{SkinName}_',
    e.g., 'arm_lower_far', 'head_1', 'hand_far_1_fistBack'.
    """
    key = part_key.lower()
    # Order matters: check more specific patterns first
    if key.startswith("head"):
        return "head"
    if key.startswith("torso"):
        return "torso"
    if key.startswith("arm_upper"):
        return "arm_upper"
    if key.startswith("arm_lower"):
        return "arm_lower"
    if key.startswith("hand"):
        return "hand"
    if key.startswith("leg_upper"):
        return "leg_upper"
    if key.startswith("leg_lower"):
        return "leg_lower"
    if key.startswith("foot"):
        return "foot"
    if key.startswith("waist"):
        return "waist"
    if key.startswith("neck"):
        return "neck"
    return "torso"  # generic fallback


class ImageGenerator(ABC):
    @abstractmethod
    def generate(self, prompt: str, width: int, height: int, seed: int) -> Image.Image:
        """Generate an RGBA image of the given size."""
        ...


class PlaceholderGenerator(ImageGenerator):
    """Generates colored rectangles with part labels for pipeline testing."""

    # Distinct colors per body part category
    COLORS = {
        "head": (255, 100, 100, 220),
        "torso": (100, 100, 255, 220),
        "arm_upper": (100, 255, 100, 220),
        "arm_lower": (150, 255, 100, 220),
        "hand": (255, 255, 100, 220),
        "leg_upper": (255, 100, 255, 220),
        "leg_lower": (200, 100, 255, 220),
        "foot": (100, 255, 255, 220),
        "waist": (255, 200, 100, 220),
        "neck": (200, 200, 200, 220),
    }

    def __init__(self, part_category: str = "torso"):
        self.part_category = part_category

    def generate(self, prompt: str, width: int, height: int, seed: int) -> Image.Image:
        color = self.COLORS.get(self.part_category, (180, 180, 180, 220))
        img = Image.new("RGBA", (width, height), color)
        return img


class FalFluxGenerator(ImageGenerator):
    """Generates images using fal.ai FLUX.1 [dev] + BiRefNet background removal."""

    def __init__(self):
        try:
            import fal_client  # noqa: F401
            self._fal = fal_client
        except ImportError:
            raise ImportError(
                "fal-client is required for the 'fal' backend. "
                "Install it with: pip install fal-client"
            )
        if not os.environ.get("FAL_KEY"):
            raise EnvironmentError(
                "FAL_KEY environment variable must be set. "
                "Get your key at https://fal.ai/dashboard/keys"
            )

    def generate(self, prompt: str, width: int, height: int, seed: int) -> Image.Image:
        # Step A: Generate image via FLUX.1 [dev]
        # Use 512x512 min for quality, we'll resize later
        gen_w = max(512, width)
        gen_h = max(512, height)
        # Keep aspect ratio close to target
        aspect = width / height if height > 0 else 1.0
        if aspect > 1:
            gen_h = 512
            gen_w = min(1024, int(512 * aspect))
        else:
            gen_w = 512
            gen_h = min(1024, int(512 / aspect))
        # Round to multiple of 8 (required by diffusion models)
        gen_w = (gen_w // 8) * 8
        gen_h = (gen_h // 8) * 8

        result = self._fal.run(
            "fal-ai/flux/dev",
            arguments={
                "prompt": prompt,
                "image_size": {"width": gen_w, "height": gen_h},
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
                "seed": seed,
                "output_format": "png",
                "num_images": 1,
            },
        )
        image_url = result["images"][0]["url"]

        # Step B: Remove background via BiRefNet
        bg_result = self._fal.run(
            "fal-ai/birefnet/v2",
            arguments={
                "image_url": image_url,
                "model": "General Use (Light)",
                "output_format": "png",
            },
        )
        transparent_url = bg_result["image"]["url"]

        # Download the transparent image
        response = urlopen(transparent_url)
        img = Image.open(BytesIO(response.read())).convert("RGBA")
        return img


# ---------------------------------------------------------------------------
# Post-processing pipeline
# ---------------------------------------------------------------------------

def postprocess(
    img: Image.Image,
    region: AtlasRegion,
) -> Image.Image:
    """Resize, rotate, and apply PMA to fit an image into an atlas region."""
    # Target size is the logical (un-rotated) dimensions
    target_w = region.logical_width
    target_h = region.logical_height

    # Resize to logical dimensions using Lanczos
    img = img.resize((target_w, target_h), Image.LANCZOS)

    # Rotate 90 CW if the atlas region is stored rotated
    if region.rotate == 90:
        # PIL rotate is CCW, so rotate -90 (or 270) for CW
        img = img.transpose(Image.ROTATE_270)

    # Apply pre-multiplied alpha (PMA) if the atlas page uses it
    if region.page.pma:
        arr = np.array(img, dtype=np.float32)
        alpha = arr[:, :, 3:4] / 255.0
        arr[:, :, :3] = arr[:, :, :3] * alpha
        img = Image.fromarray(arr.astype(np.uint8), "RGBA")

    return img


# ---------------------------------------------------------------------------
# Atlas compositor
# ---------------------------------------------------------------------------

def composite(
    atlas_png_path: str,
    regions_with_images: list[tuple[AtlasRegion, Image.Image]],
    output_path: str,
    backup: bool = True,
):
    """Composite processed images into the atlas PNG at region positions."""
    if backup:
        bak_path = atlas_png_path + ".bak"
        if not os.path.exists(bak_path):
            shutil.copy2(atlas_png_path, bak_path)
            print(f"  Backed up original to {bak_path}")
        else:
            print(f"  Backup already exists at {bak_path}")

    atlas = Image.open(atlas_png_path).convert("RGBA")

    for region, img in regions_with_images:
        # Clear the region rectangle
        clear = Image.new("RGBA", (region.width, region.height), (0, 0, 0, 0))
        atlas.paste(clear, (region.x, region.y))
        # Paste the new image
        atlas.paste(img, (region.x, region.y))

    atlas.save(output_path)
    print(f"  Saved composite atlas to {output_path}")


# ---------------------------------------------------------------------------
# Extract existing skin regions
# ---------------------------------------------------------------------------

def extract_regions(
    atlas_png_path: str,
    skin_regions: dict[str, AtlasRegion],
    output_dir: str,
):
    """Extract existing skin regions from the atlas as separate PNGs."""
    atlas = Image.open(atlas_png_path).convert("RGBA")
    os.makedirs(output_dir, exist_ok=True)

    for part_key, region in skin_regions.items():
        crop = atlas.crop((
            region.x,
            region.y,
            region.x + region.width,
            region.y + region.height,
        ))
        safe_name = part_key.replace("/", "_")
        out_path = os.path.join(output_dir, f"{safe_name}.png")
        crop.save(out_path)
        print(f"  Extracted {part_key} ({region.width}x{region.height}) -> {out_path}")


# ---------------------------------------------------------------------------
# Restore from backup
# ---------------------------------------------------------------------------

def restore_backup(atlas_png_path: str):
    """Restore heroes.png from backup."""
    bak_path = atlas_png_path + ".bak"
    if not os.path.exists(bak_path):
        print(f"Error: No backup found at {bak_path}")
        sys.exit(1)
    shutil.copy2(bak_path, atlas_png_path)
    print(f"Restored {atlas_png_path} from {bak_path}")


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def generate_skin(
    prompt: str,
    skin_name: str,
    atlas_path: str,
    png_path: str,
    backend: str = "fal",
    seed: int = 42,
    preview_dir: Optional[str] = None,
    backup: bool = True,
    dry_run: bool = False,
):
    """Full pipeline: generate art for each body part and composite into atlas."""
    print(f"Parsing atlas: {atlas_path}")
    pages, atlas_regions = parse_atlas(atlas_path)
    print(f"  Found {len(atlas_regions)} unique regions across {len(pages)} page(s)")

    print(f"Finding skin '{skin_name}' regions in atlas...")
    skin_regions = get_skin_regions(atlas_regions, skin_name)
    print(f"  Found {len(skin_regions)} regions")

    if dry_run:
        print("\nDry run — regions that would be modified:")
        for part_key, region in sorted(skin_regions.items()):
            rot = f" (rotated 90)" if region.rotate == 90 else ""
            print(
                f"  {part_key}: {region.name} at ({region.x},{region.y}) "
                f"{region.width}x{region.height}{rot}"
            )
        return

    style = "2D game sprite, cartoon style, thick outlines, cel-shaded"
    regions_with_images: list[tuple[AtlasRegion, Image.Image]] = []

    if preview_dir:
        os.makedirs(preview_dir, exist_ok=True)

    for part_key, region in sorted(skin_regions.items()):
        part_category = classify_body_part(part_key)
        part_template = PART_PROMPTS.get(part_category, "{style}")
        part_prompt = part_template.format(style=f"{prompt}, {style}")
        full_prompt = f"2D game sprite, {part_prompt}, white background, centered"

        print(f"\n  Generating: {part_key} ({part_category})")
        print(f"    Region: {region.logical_width}x{region.logical_height} "
              f"(stored: {region.width}x{region.height}, rotate={region.rotate})")

        # Create generator
        if backend == "placeholder":
            generator = PlaceholderGenerator(part_category=part_category)
        elif backend == "fal":
            generator = FalFluxGenerator()
        else:
            raise ValueError(f"Unknown backend: {backend}")

        # Generate
        raw_img = generator.generate(
            full_prompt,
            region.logical_width,
            region.logical_height,
            seed,
        )

        # Save raw preview
        if preview_dir:
            safe_name = part_key.replace("/", "_")
            raw_img.save(os.path.join(preview_dir, f"{safe_name}_raw.png"))

        # Post-process
        processed = postprocess(raw_img, region)

        # Save processed preview
        if preview_dir:
            safe_name = part_key.replace("/", "_")
            processed.save(os.path.join(preview_dir, f"{safe_name}_processed.png"))

        regions_with_images.append((region, processed))

    # Composite
    print(f"\nCompositing {len(regions_with_images)} regions into atlas...")
    composite(png_path, regions_with_images, png_path, backup=backup)
    print("\nDone! Run the skins demo to see the result.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate AI character skins for the Spine skins demo"
    )
    parser.add_argument(
        "--prompt", type=str, default="",
        help="Style prompt for the character (e.g., 'cyberpunk robot ninja')"
    )
    parser.add_argument(
        "--skin", type=str, default="Assassin",
        help="Target skin name to overwrite (default: Assassin)"
    )
    parser.add_argument(
        "--backend", type=str, default="fal", choices=["fal", "placeholder"],
        help="Image generation backend (default: fal)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for consistent generation (default: 42)"
    )

    # Path arguments with defaults relative to this script
    script_dir = Path(__file__).resolve().parent
    default_assets = script_dir.parent / "assets"
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
    parser.add_argument(
        "--preview-dir", type=str, default=None,
        help="Directory to save individual part previews"
    )
    parser.add_argument(
        "--backup", action="store_true", default=True,
        help="Backup original heroes.png before modification (default: True)"
    )
    parser.add_argument(
        "--no-backup", action="store_false", dest="backup",
        help="Skip backup of original heroes.png"
    )

    # Special modes
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List regions that would be modified, no file changes"
    )
    parser.add_argument(
        "--restore", action="store_true",
        help="Restore heroes.png from backup"
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Extract existing skin regions as separate PNGs"
    )
    parser.add_argument(
        "--extract-dir", type=str, default=None,
        help="Output directory for --extract (default: ./extracted_{skin})"
    )

    args = parser.parse_args()

    # Handle --restore
    if args.restore:
        restore_backup(args.png)
        return

    # Handle --extract
    if args.extract:
        pages, atlas_regions = parse_atlas(args.atlas)
        skin_regions = get_skin_regions(atlas_regions, args.skin)
        extract_dir = args.extract_dir or f"./extracted_{args.skin}"
        print(f"Extracting {len(skin_regions)} regions for skin '{args.skin}'...")
        extract_regions(args.png, skin_regions, extract_dir)
        return

    # Validate prompt for generation
    if not args.prompt and not args.dry_run:
        parser.error("--prompt is required for generation (or use --dry-run)")

    generate_skin(
        prompt=args.prompt,
        skin_name=args.skin,
        atlas_path=args.atlas,
        png_path=args.png,
        backend=args.backend,
        seed=args.seed,
        preview_dir=args.preview_dir,
        backup=args.backup,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
