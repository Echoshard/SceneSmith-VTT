# Scene Smith

> **The Lightweight Toolkit**

Scene Smith is a fast, self-contained tabletop RPG virtual tabletop and campaign utility suite built on Python Flask and native HTML5/JS. It keeps session management simple while providing DMs and players with a complete suite of lightweight tools.

---

## The 8 Core Tools

1. **Player VTT** (`/player`)  
   Join active game sessions, view scene maps, move allowed tokens, measure distances with ruler mode, and roll 3D dice with real-time network sync.

2. **DM VTT** (`/dm`)  
   Full Dungeon Master control: create scenes, place tokens, paint terrain, track initiative, manage music, push snap views, and drop pings.

3. **DM Media Manager** (`/dmadmin`)  
   Organize campaign media in folders, upload token images/videos, manage documents, view passwords, and add media directly to active scenes.

4. **Player Files** (`/player-files`)  
   Player-accessible media library for browsing and downloading session handouts, maps, images, and campaign documents. Includes a password-protected DM mode.

5. **Simple Dice Roller** (`/dice`)  
   Standalone 3D physics dice roller for standard polyhedral dice (`d4` through `d100`), custom math formulas (`2d6+12`), and instant roll history.

6. **Token Stamp Creator** (`/token-stamp`)  
   Crop artwork into custom token borders, adjust scale/pan, pick background colors, and save directly to your DM media library.

7. **Journal** (`/notes`)  
   Dual-view campaign wiki with dedicated **Player Info** (public) and **DM Notes** (password-locked) sections, GFM rendering, search, and `[[wiki-links]]`.

8. **Cannon Fodder Maker** (`/bestiary`)  
   Instant level 1–20 minion stat block generator with 6 class archetypes (**Grunt**, **Priest**, **Druid**, **Bard**, **Mage**, **Thief**), level-scaled damage cantrips, and one-click clipboard copying.

---

## Quick Start

### Easy Run (No Python pre-installed)

Double-click `runEmbedded.bat`.  
On first launch, it automatically downloads a self-contained Python runtime (~30 MB) and starts the server on port `3000`.

### Standard Python Run

```sh
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### Server Access & Default Passwords

- Portal Home: `http://localhost:3000/`
- DM View: `http://localhost:3000/dm`
- Player View: `http://localhost:3000/player`
- **DM Password**: `DMCODE`
- **Player Password**: `PLAY`

*(Passwords can be changed inside DM Media Manager)*

---

## Technology Stack

- **Backend**: Python 3, Flask, Flask-SocketIO, Werkzeug
- **Frontend**: Vanilla JavaScript, HTML5 Canvas, Three.js (3D Dice), Font Awesome

---

## License

Scene Smith is licensed under **GPL-3.0**.
