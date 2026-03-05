# Extract Skin Tool

Extracts a single skin from the shared heroes skeleton (`demos.json` + `heroes.png` + `heroes.atlas`) into standalone Spine files that any Spine runtime can load independently.

## Output

For a given skin (e.g., Assassin), produces:
- `assassin.json` — skeleton JSON with only `default` + target skin
- `assassin.png` — repacked texture atlas (typically 512x512)
- `assassin.atlas` — atlas metadata for the new PNG
- `viewer.html` — standalone browser viewer with animation loop

## Setup

```bash
cd spine-webgl/demos/tools
python -m venv .venv
source .venv/bin/activate
pip install Pillow
```

## Usage

### List available skins

```bash
python extract_skin.py --list-skins
```

### Extract a skin

```bash
python extract_skin.py --skin Assassin --output-dir ./assassin/
```

### Custom input paths

```bash
python extract_skin.py --skin Assassin \
  --json ../assets/demos.json \
  --atlas ../assets/heroes.atlas \
  --png ../assets/heroes.png \
  --output-dir ./assassin/
```

## Available Skins

Run `--list-skins` to see the full list. The skin names come from the `skins` array in `demos.json` (under `data.heroes.skins`). As of writing:

| Skin Name | Atlas Prefix |
|-----------|-------------|
| Assassin | Assassin/ |
| Beardy | BeardyBuck/ |
| Buck | Buck/ |
| Chuck | Chuck/ |
| Commander | Commander/ |
| Ducky | Duck/ |
| Dummy | Dummy/ |
| Fletch | Fletch/ |
| Gabriel | GabrielCaine/ |
| MetalMan | MetalMan-Blue/ |
| Pamela-1 | PamelaFrost/ |
| Pamela-2 | PamelaFrost-02/ |
| Pamela-3 | PamelaFrost-03/ |
| Pamela-4 | PamelaFrost-04/ |
| Pamela-5 | PamelaFrost-05/ |
| Stumpy | StumpyPete/ |
| Truck | Truck/ |
| Turbo | TurboTed/ |
| Young | YoungBuck/ |

The **Skin Name** column is what you pass to `--skin`. The atlas prefix column shows the corresponding region prefix in `heroes.atlas` — the tool resolves this automatically via the JSON attachment `name` fields, so you don't need to know the prefix.

## Testing the Viewer

```bash
# From the spine-ts root
cd ../../..
npm run dev

# Open in browser
# http://127.0.0.1:8080/spine-webgl/demos/tools/assassin/viewer.html
```

The viewer loads `spine-webgl.js` from `../../dist/iife/spine-webgl.js` (relative to the output directory), so the output directory must remain under `spine-webgl/demos/tools/` for the viewer to work with the dev server.

## Verification

The tool runs automated checks after extraction:
- All 3 data files exist
- JSON contains required keys (`skeleton`, `bones`, `slots`, `skins`, `animations`)
- Every attachment `name` in JSON has a matching atlas region
- PNG dimensions match the atlas page `size`
- All region bounds fit within the PNG
