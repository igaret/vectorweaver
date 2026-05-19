# VectorWeaver

VectorWeaver is an offline WYSIWYG vector-image editor for `.svg` files. It is designed as a practical Dreamweaver-style visual/source workflow for SVG: you can draw and edit visually on a canvas, inspect and edit the generated SVG source, then apply the source back to the visual editor.

The app intentionally uses only Python's standard library, especially Tkinter for the desktop UI and ElementTree for SVG import/export. It does not fetch packages from the internet and does not require internet access at runtime.

## Main Features

- Offline Windows desktop application source code.
- No web/CDN/runtime internet dependencies.
- Visual SVG canvas editor.
- SVG source-code panel with refresh/apply workflow.
- Shape tools: rectangle, ellipse, line, freehand path/brush, and text.
- Photoshop-inspired controls: fill color, stroke color, stroke width, opacity, eyedropper, eraser, duplicate, layer ordering, visibility toggles, zoom, grid, snap-to-grid, scale selected object, undo, redo.
- Layers/object panel for selecting and toggling SVG objects.
- Open/save/export `.svg` files.

## Requirements

For source execution:

- Windows 10 or newer.
- Python 3.10+ with Tkinter enabled. The official Windows Python installer normally includes Tkinter.

For native `.exe` production builds:

- PyInstaller must already be installed locally. The included `deploy.bat` will not download it. This is intentional so deployment can remain offline.

If PyInstaller is unavailable, `deploy.bat` still creates a production folder with a `VectorWeaver.bat` launcher that runs the app using installed Python 3.

## Run from Source on Windows

Open Command Prompt in this folder and run:

```bat
py -3 src\vectorweaver.py
```

If `py` is unavailable, use:

```bat
python src\vectorweaver.py
```

## Deploy Production Package on Windows

Double-click:

```bat
deploy.bat
```

or run it from Command Prompt:

```bat
deploy.bat
```

The script creates:

```text
dist\VectorWeaver-production\
```

Inside that folder you will find:

- `VectorWeaver.bat` — launcher using installed Python 3.
- `VectorWeaver.vbs` — quiet launcher wrapper.
- `src\vectorweaver.py` — production source copy.
- `VectorWeaver.exe` — only if PyInstaller is already available locally.

## Offline EXE Build Notes

This project does not vendor PyInstaller because that would add a third-party dependency package. If your Windows machine already has PyInstaller installed from an offline-approved wheelhouse, `deploy.bat` automatically detects it and builds a one-file, windowed executable.

To prepare a fully offline PyInstaller environment, your organization can download PyInstaller and its wheels on an internet-connected machine, move the wheelhouse to the offline Windows machine, install from local files, then rerun `deploy.bat`. VectorWeaver itself still has no internet dependency.

## Current SVG Import Limitations

VectorWeaver imports common editable SVG elements: `rect`, `ellipse`, `circle`, `line`, `polyline`, simple `path` data made mainly of numeric M/L coordinates, and `text`. Complex SVG files containing gradients, filters, masks, clipping paths, embedded images, CSS stylesheets, transforms, symbols, and advanced Bézier path commands may open partially or may need source-level editing.

The app always saves clean editable SVG containing the supported object types.

## Suggested Test

1. Run `py -3 src\vectorweaver.py`.
2. Select Rectangle and draw a rectangle.
3. Choose a fill color and stroke color.
4. Select Text and add a label.
5. Use the Layers panel to select objects.
6. Press Save and write an `.svg` file.
7. Reopen that `.svg` with Open SVG.
8. Edit the SVG source panel and click Apply to Canvas.

## Project Layout

```text
vectorweaver/
  deploy.bat
  README.md
  src/
    vectorweaver.py
  assets/
  dist/
```
