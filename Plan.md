# SceneSmith VTT & Portal Architecture

SceneSmith VTT is a Python Flask + WebSockets Virtual Tabletop engine equipped with an 8-tool portal system for D&D / TTRPG session management.

---

## Complete 8-Tool Portal Suite

1. **Player View** (`/player`)
   - Interactive VTT map canvas & token view for player displays.
2. **DM View** (`/dm`)
   - DM control panel, scene builder, fog of war, weather particles, & terrain brush.
3. **DM Media Manager** (`/dmadmin`)
   - Media folder browser, upload center, asset manager, and password settings.
4. **Player Files** (`/player-files`)
   - Shared player handouts, maps, documents, and reference PDFs.
5. **Simple Dice Roller** (`/dice`)
   - 3D physics dice roller powered by Three.js with Advantage/Disadvantage and roll history.
6. **Token Stamp Creator** (`/token-stamp`)
   - HTML5 Canvas token creator with Circle, Hexagon, Octagon, Square, and Ring borders.
7. **Inkwell Dual Wiki** (`/notes` / `/player-notes`)
   - Inkwell-style dual wiki with private DM Notes & public Player Info, drag-and-drop image upload, sidebar folder CRUD, connected scrolling, and TTS read aloud.
8. **5e Bestiary & Cannon Fodder Generator** (`/bestiary`)
   - 5e.tools-styled stat block card viewer with preset monsters (Cannon Fodder, Hover Drone, Mercenary) and a level 1–20 Mage, Grunt, and Thief generator.

---

## Server Deployment

- **Render 100% Free Tier**: Pre-configured via [render.yaml](file:///u:/GitHub/DocTest/SceneSmith-VTT/render.yaml).
- **Execution**: Run via `runEmbedded.bat` locally or deploy via GitHub to Render.