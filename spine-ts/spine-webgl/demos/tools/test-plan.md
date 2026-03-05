# Commands to Run (in order)

All commands run from `spine-webgl/demos/tools/`.

## 1. Install dependencies (if not already done)

```bash
cd spine-webgl/demos/tools
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Dry-run — verify atlas parsing finds all 22 regions

```bash
python generate_skin.py --dry-run --skin Assassin
```

## 3. Extract existing Assassin regions — visually inspect them

```bash
python generate_skin.py --extract --skin Assassin --extract-dir ./extracted_Assassin
```
Open `./extracted_Assassin/` and verify the 22 PNGs look like correct body parts.

## 4. Test with placeholder backend — colored rectangles, no API calls

```bash
python generate_skin.py --prompt "test" --skin Assassin --backend placeholder --preview-dir ./preview/
```
This overwrites `heroes.png` (backs up to `heroes.png.bak` automatically).

## 5. View the result in the skins demo

```bash
cd ../../..   # back to spine-ts root
npm run dev
```
Open http://127.0.0.1:8080 → skins demo → select "Assassin" skin → you should see colored rectangles. Also test "Randomize Attachments".

## 6. Restore original atlas

```bash
cd spine-webgl/demos/tools
python generate_skin.py --restore
```

## 7. Generate with fal.ai (requires FAL_KEY)

```bash
export FAL_KEY=your-api-key-here
python generate_skin.py \
    --prompt "cyberpunk robot ninja" \
    --skin Assassin \
    --backend fal \
    --seed 42 \
    --preview-dir ./preview/
```
Inspect `./preview/` for individual body parts before viewing in the demo.

## 8. View AI-generated result

```bash
cd ../../..
npm run dev
```
Open http://127.0.0.1:8080 → skins demo → select "Assassin".

## 9. Restore when done

```bash
cd spine-webgl/demos/tools
python generate_skin.py --restore
```
