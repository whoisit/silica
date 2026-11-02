# Silica

**A Softimage layer for Blender: frontend, skin and workflow.**

Silica is a free, open-source extension for Blender 5.2 that brings back the Softimage way of working: the
theme, the layout, the menus, the MCP, the Explorer, property pages, viewport views and the core keys. One click
switches it all off and gives you plain Blender again. It also opens real Softimage `.scn` files, rebuilding
meshes, primitives, cameras, lights, materials, UVs and image textures.

> **Early release (0.1).** Made for ex-Softimage artists who want their hands to feel at home in Blender.
> A lot is still missing (see [What's not there yet](#whats-not-there-yet)). Feedback is very welcome.

## Install

1. Download `silica-<version>.zip` from the **Releases** page. You don't need to unzip it.
2. In Blender 5.2: **Edit > Preferences > Get Extensions**, open the **⌄** menu at the top right,
   choose **Install from Disk...** and pick the zip.
3. Click **SI** at the right end of Blender's top bar to turn Softimage mode on. Click it again to go back
   to plain Blender. Your own theme is backed up and restored.

Requires **Blender 5.2** or newer.

## What's in it

- **Look and layout:** Softimage theme and colours, the four-view layout with the module toolbar on the
  left and the MCP on the right, viewport headers with the view letter and View / Display menus.
- **Menus:** the Softimage main menu bar. Items that don't do anything yet are shown greyed out, so you can
  see what's coming.
- **Keys:** sticky (tap) and supra (hold) tools.
  - S navigation, Z pan/zoom, O orbit, P dolly
  - V / C / X translate / rotate / scale, Space select
  - T / E / Y / U / I component selection
  - A / F frame all / selection, R reset camera, H hide, G grid, D duplicate, K key
  - Q render region, F12 maximize the view under the mouse, Enter opens the property page
  - 1-4 module toolbars, 5-0 floating Browser, Layers, Render Tree, Explorer, Schematic, Animation Editor
- **Explorer:** the scene tree, with F to find the selected object.
- **Property Editor (PPG)** for the selection.
- **Get > Primitive** with Softimage's default sizes and subdivisions.
- **Memo cams** (four stored views per viewport) and view maximize (full, horizontal, vertical).
- **Render Tree** colours and a preset panel; Tab adds a node.
- **Import Softimage scenes:** **File > Import > Softimage Scene (.scn)**. It reads the scene file itself; you
  don't need Softimage installed. You get:
  - frozen meshes and live primitives, with their transforms and hierarchy
  - cameras and lights
  - materials (mapped to Principled BSDF), UV maps and image textures

## What's not there yet

- Many keys and tools are missing. Examples: M to tweak components, +/− subdivision, Reset SRT, isolate
  selection.
- Animation, envelopes and weights, the Mixer, render passes and partitions, ICE.
- Import: no animation yet. Live primitives get no UVs. Some scenes from older Softimage versions only
  partly load.

Please report what you miss most. If a `.scn` won't import, open an issue with your Blender version and
what the import report says. **Don't attach client or confidential scenes to public issues.**

## Credits

Inspired by Jake Denham's video ["I Rebuilt 3ds Max With AI"](https://www.youtube.com/watch?v=74TsKdNWEaA).
Similar projects worth a look:
[maya-workflow-kit-for-blender](https://github.com/5hyuns/maya-workflow-kit-for-blender) (Maya, by 5hyuns) and
[SItoB](https://github.com/land-Y/SItoB) (Softimage-style modeling tools, by cvELD).

## Not affiliated with Autodesk

Silica is an independent project. It is **not affiliated with, endorsed by, sponsored by or supported by
Autodesk, Inc.**, and it is not an official Autodesk product. Please don't contact Autodesk for help with it.
It is not a Blender Foundation project either.

Autodesk, Softimage and XSI are registered trademarks or trademarks of Autodesk, Inc. in the USA and other
countries. Blender is a trademark of the Blender Foundation. These names are used only to describe the
workflow Silica recreates and the software it runs on.

Silica recreates behaviour only. It contains no Autodesk code, icons, images or documentation text.

## License

GPL-3.0-or-later. Copyright (C) 2026 Alex Doss. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Provided as is,
without warranty.
