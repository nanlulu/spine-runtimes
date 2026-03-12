# panda_to_skin.py

Converts an exploded panda character sheet (`panda.png`) into a Spine-compatible atlas texture that maps onto the Assassin skeleton. The script segments the character sheet into body parts, assigns them to atlas regions, and composites a new `assassin.png` for the `color-block/` skin.

## Prerequisites

- Python 3.10+
- Dependencies: `numpy`, `Pillow`, `scipy`
- `generate_skin.py` must be in the same directory (provides `parse_atlas` and `AtlasRegion`)

## Usage

```bash
# Default: reads panda.png, writes to color-block/assassin.png
python panda_to_skin.py

# Custom input/output
python panda_to_skin.py --input panda.png --output color-block/assassin.png

# Save debug images to debug/
python panda_to_skin.py --debug
```

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `panda.png` | Input exploded character sheet |
| `--output` | `color-block/assassin.png` | Output atlas PNG |
| `--atlas` | `color-block/assassin.atlas` | Spine atlas file to read region definitions from |
| `--tolerance` | `30` | Color tolerance for background flood-fill removal |
| `--debug` | off | Save intermediate images to `debug/` directory |

## How It Works

The pipeline has 5 stages:

### 1. Background Removal

Uses BFS flood-fill from all border pixels to identify the background. Unlike simple color thresholding, this preserves interior white areas (like the panda's face) that aren't connected to the border. The corner pixel colors are averaged to determine the background color, and a configurable tolerance controls how aggressively neighboring pixels are matched.

### 2. Blob Segmentation

Runs connected-component labeling (`scipy.ndimage.label`) on the alpha channel to find distinct body-part blobs. Blobs smaller than 200 pixels are discarded as noise. Each blob is cropped to its tight bounding box.

### 3. Spatial Body-Part Assignment

Assigns blobs to body-part names based on their spatial position in the A-pose layout:

- **Head**: Topmost blob with area > 5000 pixels
- **Neck**: Small blob near center, just below the head
- **Torso**: Largest remaining blob near center
- **Waist**: Smaller blob below the torso, near center
- **Limbs**: Remaining blobs are split into left/right of the image center. Each side is sorted top-to-bottom and assigned: `arm_upper`, `hand` (boxing glove), `leg_upper`, `leg_lower`, `foot`. The hand blob is reused for `arm_lower` since the panda has no separate forearm piece.

The image left side maps to "far" and right side to "near" (Spine convention where the character faces right).

### 4. Orientation Correction

Each body part is rotated to match the expected bone-local orientation in the Spine skeleton:

- **Arms and upper legs**: Rotated so the principal axis is horizontal
- **Lower legs**: Rotated so the principal axis is vertical
- **Head, torso, hands, feet**: No rotation applied

The principal axis is computed via a 2D covariance matrix of non-transparent pixel positions. Rotations smaller than 5 degrees are skipped.

### 5. Atlas Compositing

Parses the Spine `.atlas` file to get region positions and sizes for all `Assassin/Assassin_*` entries. Each body part is:

1. Resized to fit its target atlas region (aspect-ratio preserving)
2. Centered on a transparent canvas matching the region dimensions
3. Rotated 90 degrees CW if the atlas stores that region rotated
4. Premultiplied alpha (PMA) applied if the atlas page requires it
5. Pasted onto the output atlas at the correct coordinates

## Region Mapping

The script maps 20 atlas region suffixes to 15 body-part keys. Some regions share the same source image (e.g., `head_1` and `head_2_injured` both use `head`; fist-back and fist-palm variants both use the same `hand` crop).

## Debug Output

With `--debug`, intermediate images are saved to `debug/`:

| Prefix | Content |
|--------|---------|
| `01_background_removed.png` | Full image after flood-fill background removal |
| `02_blob_*.png` | Individual segmented blobs |
| `03_part_*.png` | Blobs assigned to body-part names |
| `03b_oriented_*.png` | Body parts after orientation correction |
| `04_fitted_*.png` | Final fitted images per atlas region |
