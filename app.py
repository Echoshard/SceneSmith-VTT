import json
import mimetypes
import os
import random
import re
import shutil
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"
SCENES_DIR = DATA_DIR / "scenes"
SECRET_DIR = DATA_DIR / "private"
SECRET_FILE = SECRET_DIR / "secrets.txt"
LEGACY_SECRET_FILE = BASE_DIR / "secret.txt"
UPLOADS_DIR = PUBLIC_DIR / "uploads"
MEDIA_DIR = PUBLIC_DIR / "media"
PLAYER_MEDIA_DIR = PUBLIC_DIR / "player-media"
MUSIC_DIR = PUBLIC_DIR / "music"
NOTES_FILE = DATA_DIR / "sticky-notes.json"

DEFAULT_SECRETS = {
    "DM_PASSWORD": "DMCODE",
    "PLAYER_PASSWORD": "PLAY",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".mov"}
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log"}
DOC_EXTS = PDF_EXTS | TEXT_EXTS
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | DOC_EXTS
MUSIC_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}


def now_ms():
    return str(int(time.time() * 1000))


def parse_secrets(raw):
    trimmed = raw.strip()
    if "=" not in trimmed:
        secrets = dict(DEFAULT_SECRETS)
        secrets["DM_PASSWORD"] = trimmed or DEFAULT_SECRETS["DM_PASSWORD"]
        return secrets

    secrets = dict(DEFAULT_SECRETS)
    for line in raw.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        key = key.strip()
        if key:
            secrets[key] = value.strip()
    return secrets


def format_secrets(secrets):
    return "\n".join([
        "# Passwords can be edited here or from the Media Library password tab.",
        "# These values stay server-side and are never sent to browser JavaScript.",
        f"DM_PASSWORD={secrets.get('DM_PASSWORD') or DEFAULT_SECRETS['DM_PASSWORD']}",
        f"PLAYER_PASSWORD={secrets.get('PLAYER_PASSWORD') or DEFAULT_SECRETS['PLAYER_PASSWORD']}",
        "",
    ])


def ensure_secret_storage():
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists() and LEGACY_SECRET_FILE.exists():
        try:
            LEGACY_SECRET_FILE.replace(SECRET_FILE)
        except OSError:
            shutil.copyfile(LEGACY_SECRET_FILE, SECRET_FILE)
            LEGACY_SECRET_FILE.unlink(missing_ok=True)


def read_secrets():
    ensure_secret_storage()
    try:
        return parse_secrets(SECRET_FILE.read_text(encoding="utf-8"))
    except OSError:
        secrets = dict(DEFAULT_SECRETS)
        SECRET_FILE.write_text(format_secrets(secrets), encoding="utf-8")
        return secrets


def safe_folder_name(value):
    return re.sub(r"[^a-zA-Z0-9_\- ]", "", value or "").strip()


def safe_relative_media_path(url):
    rel = re.sub(r"^/media/", "", url or "")
    if not rel or ".." in rel or rel.startswith(("/", "\\")):
        return None
    return rel


def safe_relative_player_media_path(url):
    rel = re.sub(r"^/player-media/", "", url or "")
    if not rel or ".." in rel or rel.startswith(("/", "\\")):
        return None
    return rel


def get_media_type(name):
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in TEXT_EXTS:
        return "text"
    return None


class SceneStore:
    def __init__(self):
        self.active_scene_id = None
        self.scenes = {}
        SCENES_DIR.mkdir(parents=True, exist_ok=True)

    def path_for(self, scene_id):
        return SCENES_DIR / f"{scene_id}.json"

    def add_scene(self, scene):
        self.scenes[scene["sceneId"]] = scene

    def load_scene(self, scene_id):
        if scene_id in self.scenes:
            return self.scenes[scene_id]
        path = self.path_for(scene_id)
        scene = json.loads(path.read_text(encoding="utf-8"))
        self.scenes[scene_id] = scene
        return scene

    def save_scene(self, scene):
        SCENES_DIR.mkdir(parents=True, exist_ok=True)
        self.path_for(scene["sceneId"]).write_text(json.dumps(scene, indent=2), encoding="utf-8")

    def get_all_scenes(self):
        scenes = []
        for path in SCENES_DIR.glob("*.json"):
            try:
                scene = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scenes.append({
                "sceneId": scene.get("sceneId"),
                "sceneName": scene.get("sceneName"),
                "order": scene.get("order", 0),
            })
        scenes.sort(key=lambda item: item.get("order", 0))
        return scenes

    def update_scene(self, scene):
        self.scenes[scene["sceneId"]] = scene
        self.save_scene(scene)

    def change_active_scene(self, scene_id):
        self.active_scene_id = scene_id

    def delete_scene(self, scene_id):
        scene = self.scenes.get(scene_id) or self.load_scene(scene_id)
        self.path_for(scene_id).unlink(missing_ok=True)
        self.scenes.pop(scene_id, None)
        for token in scene.get("tokens", []):
            image_url = token.get("imageUrl")
            self.delete_upload_if_unused(image_url)

    def update_scene_order(self, scene_order):
        for index, scene_id in enumerate(scene_order):
            scene = self.load_scene(scene_id)
            scene["order"] = index
            self.save_scene(scene)

    def is_image_used_elsewhere(self, image_url):
        if not image_url:
            return False
        for path in SCENES_DIR.glob("*.json"):
            try:
                scene = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for token in scene.get("tokens", []):
                if token.get("imageUrl") == image_url:
                    return True
        return False

    def delete_upload_if_unused(self, image_url):
        if not image_url or image_url.startswith("data:") or image_url.startswith("/media/"):
            return
        if self.is_image_used_elsewhere(image_url):
            return
        rel = image_url.lstrip("/")
        path = PUBLIC_DIR / rel
        try:
            path.unlink()
        except OSError:
            pass

    def update_token(self, scene_id, token_id, properties):
        scene = self.scenes.get(scene_id) or self.load_scene(scene_id)
        for token in scene.get("tokens", []):
            if token.get("tokenId") == token_id:
                was_hidden = bool(token.get("hidden"))
                token.update(properties or {})
                self.save_scene(scene)
                return token, was_hidden, bool(token.get("hidden"))
        return None, False, False

    def add_token(self, scene_id, token):
        scene = self.scenes.get(scene_id) or self.load_scene(scene_id)
        scene.setdefault("tokens", []).append(token)
        self.save_scene(scene)

    def remove_token(self, scene_id, token_id):
        scene = self.scenes.get(scene_id) or self.load_scene(scene_id)
        tokens = scene.setdefault("tokens", [])
        for index, token in enumerate(tokens):
            if token.get("tokenId") == token_id:
                removed = tokens.pop(index)
                self.save_scene(scene)
                self.delete_upload_if_unused(removed.get("imageUrl"))
                return removed
        return None


scene_store = SceneStore()
secrets = read_secrets()

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
app.secret_key = os.environ.get("SESSION_SECRET") or os.urandom(32)
app.config["DM_PASSWORD"] = secrets.get("DM_PASSWORD") or DEFAULT_SECRETS["DM_PASSWORD"]
app.config["PLAYER_PASSWORD"] = secrets.get("PLAYER_PASSWORD") or DEFAULT_SECRETS["PLAYER_PASSWORD"]
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

bg_color = None
grid_state = None
initiative_state = None


def require_dm():
    return bool(session.get("isDM"))


def require_player():
    return bool(session.get("isPlayer") or session.get("isDM"))


def json_body():
    return request.get_json(force=True, silent=True) or request.form.to_dict() or request.args.to_dict() or {}


@app.before_request
def redirect_static_html_names():
    if request.path == "/index.html":
        return redirect("/")
    if request.path == "/player.html":
        return redirect("/player")
    if request.path == "/dm.html":
        return redirect("/dm")
    if request.path == "/files.html":
        return redirect("/dmadmin")
    if request.path == "/player-files.html":
        return redirect("/player-files")
    if request.path == "/dice.html":
        return redirect("/dice")
    if request.path == "/token-stamp.html":
        return redirect("/token-stamp")
    if request.path == "/notes.html":
        return redirect("/notes")
    if request.path == "/bestiary.html":
        return redirect("/bestiary")
    return None


@app.after_request
def cache_headers(response):
    if request.path.lower().endswith((".html", ".css", ".js")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def portal_index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/authStatus")
def auth_status():
    return jsonify({
        "isDm": bool(session.get("isDM")),
        "isPlayer": bool(session.get("isPlayer") or session.get("isDM"))
    })


@app.get("/player")
def player_vtt_page():
    if not require_player():
        return redirect("/player-login")
    return send_from_directory(PUBLIC_DIR, "player.html")


@app.get("/player-login")
def player_login_page():
    return send_from_directory(PUBLIC_DIR, "player-login.html")


@app.post("/player-login")
def player_login():
    password = request.form.get("password") or json_body().get("password")
    if password == app.config["PLAYER_PASSWORD"]:
        session["isPlayer"] = True
        return redirect("/player")
    return 'Incorrect password. <a href="/player-login">Try again</a>'


@app.get("/dm-login")
def dm_login_page():
    return send_from_directory(PUBLIC_DIR, "dm-login.html")


@app.post("/dm-login")
def dm_login():
    password = request.form.get("password") or json_body().get("password")
    if password == app.config["DM_PASSWORD"]:
        session["isDM"] = True
        return redirect("/dm")
    return 'Incorrect password. <a href="/dm-login">Try again</a>'


@app.get("/dm")
def dm_page():
    if not require_dm():
        return redirect("/dm-login")
    return send_from_directory(PUBLIC_DIR, "dm.html")


@app.get("/dmadmin")
def files_page():
    if not require_dm():
        return redirect("/dm-login")
    return send_from_directory(PUBLIC_DIR, "files.html")


@app.get("/player-files")
def player_files_page():
    if not require_player():
        return redirect("/player-login")
    return send_from_directory(PUBLIC_DIR, "player-files.html")


@app.get("/dice")
def dice_page():
    return send_from_directory(PUBLIC_DIR, "dice.html")


@app.get("/token-stamp")
def token_stamp_page():
    return send_from_directory(PUBLIC_DIR, "token-stamp.html")


@app.get("/notes")
def notes_page():
    return send_from_directory(PUBLIC_DIR, "notes.html")


@app.get("/player-notes")
def player_notes_page():
    return send_from_directory(PUBLIC_DIR, "notes.html")


@app.get("/bestiary")
def bestiary_page():
    return send_from_directory(PUBLIC_DIR, "bestiary.html")


@app.get("/api/bestiary")
def get_bestiary_list():
    bestiary_dir = DATA_DIR / "bestiary"
    bestiary_dir.mkdir(parents=True, exist_ok=True)

    presets = [
        {
            "name": "Cannon Fodder",
            "type": "Small / Medium Minion",
            "hp": 9,
            "ac": 11,
            "init": "+0",
            "perception": "+0",
            "stats": "STR +0 | DEX +0 | CON +0 | INT +0 | WIS +0 | CHA +0",
            "saves": "None",
            "actions": [
                {"name": "Light Pistol", "detail": "Attack +2, 1d6 piercing damage"}
            ],
            "traits": [
                {"name": "Utility Drone (1/Day)", "detail": "Grants Help advantage on one ability check or attack roll."}
            ],
            "skills": "+4 Persuade"
        },
        {
            "name": "Hover Drone",
            "type": "Small Flying Automaton (60ft)",
            "hp": 20,
            "ac": 15,
            "init": "+2",
            "perception": "+0",
            "stats": "STR +0 | DEX +2 | CON +2 | INT +2 | WIS +0 | CHA +0",
            "saves": "DEX +3 | CON +4",
            "actions": [
                {"name": "Laser Blaster", "detail": "Ranged Attack +2 (Laser blaster) 1d6 radiant damage"}
            ],
            "traits": [
                {"name": "Hover Recon", "detail": "Can fly up to 60ft and hover in place without provoking opportunity attacks."}
            ],
            "skills": "Perception +0"
        },
        {
            "name": "Mercenary",
            "type": "Medium Humanoid",
            "hp": 45,
            "ac": 14,
            "init": "+1",
            "perception": "+4",
            "stats": "STR +2 | DEX +1 | CON +2 | INT +0 | WIS +0 | CHA +0",
            "saves": "DEX +3 | CON +4",
            "actions": [
                {"name": "Combat Sword", "detail": "Melee Attack +4 (Combat Sword) 1d10 + 2 slashing + 1d6 radiant damage"},
                {"name": "Shotgun", "detail": "Range Attack +4 (Shotgun) 2d6 + 2 piercing damage"}
            ],
            "traits": [
                {"name": "Grenade (1/Day)", "detail": "Throws a frag grenade. DC 11 Dex save, 2d8 fire damage to all targets in 15ft radius."},
                {"name": "Fire Resistance", "detail": "Takes half damage from fire attacks."}
            ],
            "skills": "Perception +4, Survival +3"
        }
    ]

    srd_monsters = []
    srd_file = DATA_DIR / "srd_monsters.json"
    if srd_file.exists():
        try:
            srd_monsters = json.loads(srd_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    custom_blocks = []
    for file in bestiary_dir.glob("*.json"):
        try:
            custom_blocks.append(json.loads(file.read_text(encoding="utf-8")))
        except Exception:
            pass

    return jsonify({"ok": True, "presets": presets, "srd": srd_monsters, "custom": custom_blocks})


@app.post("/api/generateFodder")
def generate_fodder():
    data = request.get_json(force=True, silent=True) or json_body()
    raw_arch = data.get("archetype") or request.args.get("archetype") or request.form.get("archetype") or "grunt"
    archetype_key = str(raw_arch).strip().lower()

    raw_level = data.get("level") or request.args.get("level") or request.form.get("level") or 1
    try:
        level = max(1, min(20, int(raw_level)))
    except (ValueError, TypeError):
        level = 1

    raw_name = data.get("name") or request.args.get("name") or request.form.get("name") or ""
    custom_name = str(raw_name).strip()

    # Load external JSON configuration
    config_file = DATA_DIR / "fodder_archetypes.json"
    archetypes_cfg = {}
    if config_file.exists():
        try:
            archetypes_cfg = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    ARCHETYPE_ALIASES = {
        "priest": "priest",
        "cleric": "priest",
        "druid": "druid",
        "bard": "bard",
        "mage": "mage",
        "wizard": "mage",
        "thief": "thief",
        "rogue": "thief",
        "grunt": "grunt",
        "warrior": "grunt",
        "fighter": "grunt"
    }
    target_key = ARCHETYPE_ALIASES.get(archetype_key, archetype_key)
    cfg = archetypes_cfg.get(target_key) or archetypes_cfg.get("grunt") or {}

    if not custom_name:
        custom_name = f"Level {level} {cfg.get('title', target_key.capitalize())}"

    pb = (level - 1) // 4 + 2
    primary_mod = cfg.get("baseStatVal", 3) + (level // cfg.get("statScaleDivisor", 4))
    hp = cfg.get("baseHp", 10) + (level - 1) * cfg.get("hpPerLevel", 6)
    ac = cfg.get("baseAc", 14) + (level // cfg.get("acScaleDivisor", 4))

    heal_dice = 1 + (level // 4)
    sneak_dice = (level + 1) // 2
    ray_dice = 1 + (level // 5)
    cantrip_dice = 1 if level < 5 else (2 if level < 11 else (3 if level < 17 else 4))
    attack_mod = primary_mod + pb
    ranged_mod = 1 + pb

    fmt_vars = {
        "level": level,
        "pb": pb,
        "primary_mod": primary_mod,
        "attack_mod": attack_mod,
        "ranged_mod": ranged_mod,
        "heal_dice": heal_dice,
        "sneak_dice": sneak_dice,
        "ray_dice": ray_dice,
        "cantrip_dice": cantrip_dice,
        "cantrip_d10": f"{cantrip_dice}d10",
        "cantrip_d8": f"{cantrip_dice}d8",
        "cantrip_d6": f"{cantrip_dice}d6",
        "cantrip_d4": f"{cantrip_dice}d4",
        "cantrip_d12": f"{cantrip_dice}d12",
        "dc": 8 + pb + primary_mod,
        "level_temp_hp": 15 + level * 3,
        "int_save": primary_mod + pb if cfg.get("primaryStat") == "INT" else 1 + pb,
        "wis_save": primary_mod + pb if cfg.get("primaryStat") == "WIS" else 1 + pb,
        "str_save": primary_mod + pb if cfg.get("primaryStat") == "STR" else 1 + pb,
        "dex_save": primary_mod + pb if cfg.get("primaryStat") == "DEX" else 3 + pb,
        "cha_save": primary_mod + pb if cfg.get("primaryStat") == "CHA" else 1 + pb,
        "con_save": 3 + pb,
        "rel_skill": 1 + pb,
        "med_skill": primary_mod + pb,
        "per_skill": primary_mod + pb,
        "arc_skill": primary_mod + pb,
        "hist_skill": primary_mod,
        "ath_skill": primary_mod + pb,
        "stealth_skill": primary_mod + pb + 2,
        "acro_skill": primary_mod + pb
    }

    spells_dict = cfg.get("spells") or {}
    spells_active = []
    if "cantrips" in spells_dict: spells_active.append(spells_dict["cantrips"].format(**fmt_vars))
    if level >= 1 and "level1" in spells_dict: spells_active.append(spells_dict["level1"].format(**fmt_vars))
    if level >= 3 and "level3" in spells_dict: spells_active.append(spells_dict["level3"].format(**fmt_vars))
    if level >= 5 and "level5" in spells_dict: spells_active.append(spells_dict["level5"].format(**fmt_vars))
    if level >= 7 and "level7" in spells_dict: spells_active.append(spells_dict["level7"].format(**fmt_vars))
    if level >= 9 and "level9" in spells_dict: spells_active.append(spells_dict["level9"].format(**fmt_vars))
    fmt_vars["spells"] = " | ".join(spells_active)

    stats = cfg.get("statsTemplate", "").format(**fmt_vars)
    saves = cfg.get("savesTemplate", "").format(**fmt_vars)
    skills = cfg.get("skillsTemplate", "").format(**fmt_vars)

    actions = [{"name": a["name"].format(**fmt_vars), "detail": a["detail"].format(**fmt_vars)} for a in cfg.get("actions", [])]
    traits = [{"name": t["name"].format(**fmt_vars), "detail": t["detail"].format(**fmt_vars)} for t in cfg.get("traits", [])]

    init_val = f"+{fmt_vars['primary_mod']}" if cfg.get("primaryStat") == "DEX" else "+0" if cfg.get("primaryStat") == "WIS" else f"+{2 + (level // 6)}" if cfg.get("primaryStat") == "INT" else "+1"
    percep_val = f"+{fmt_vars['primary_mod'] + pb}" if cfg.get("primaryStat") == "WIS" else f"+{2 + pb}" if cfg.get("primaryStat") == "DEX" else f"+{1 + (level // 3)}" if cfg.get("primaryStat") == "INT" else "+1"

    block = {
        "name": custom_name,
        "type": f"Level {level} {cfg.get('title', archetype_key.capitalize())}",
        "hp": hp,
        "ac": ac,
        "init": init_val,
        "perception": percep_val,
        "stats": stats,
        "saves": saves,
        "actions": actions,
        "traits": traits,
        "skills": skills
    }

    return jsonify({"ok": True, "statBlock": block})


@app.post("/api/saveStatBlock")
def save_stat_block():
    if not require_dm():
        return jsonify({"error": "DM login required"}), 401
    data = json_body()
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", data.get("name") or "")
    if not name:
        return jsonify({"error": "Invalid stat block name"}), 400
    bestiary_dir = DATA_DIR / "bestiary"
    bestiary_dir.mkdir(parents=True, exist_ok=True)
    (bestiary_dir / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.post("/saveTokenStamp")
def save_token_stamp():
    data = json_body()
    base64_data = data.get("image") or ""
    if not base64_data or not re.match(r"^data:image/(png|jpeg|webp);base64,", base64_data):
        return jsonify({"error": "Invalid image data"}), 400
    import base64
    raw_bytes = base64.b64decode(re.sub(r"^data:image/(png|jpeg|webp);base64,", "", base64_data))
    tokens_dir = MEDIA_DIR / "Tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    filename = f"stamped_token_{now_ms()}_{random.randint(100, 999)}.png"
    target = tokens_dir / filename
    target.write_bytes(raw_bytes)
    return jsonify({"ok": True, "url": f"/media/Tokens/{filename}"})


@app.post("/api/dm-login")
def api_dm_login():
    password = json_body().get("password") or request.form.get("password")
    if password == app.config["DM_PASSWORD"]:
        session["isDM"] = True
        return jsonify({"ok": True, "isDm": True})
    return jsonify({"error": "Incorrect DM password"}), 401


@app.post("/uploadWikiImage")
def upload_wiki_image():
    if not require_dm():
        return jsonify({"error": "DM login required"}), 401
    file = request.files.get("file") or request.files.get("image")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in IMAGE_EXTS:
        return jsonify({"error": "Unsupported image format"}), 400
    wiki_dir = MEDIA_DIR / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    filename = f"wiki_{now_ms()}_{secure_filename(file.filename)}"
    file.save(wiki_dir / filename)
    return jsonify({"ok": True, "url": f"/media/wiki/{filename}"})


def clean_wiki_path(path):
    clean = re.sub(r"[^a-zA-Z0-9_\-/]", "", path or "").strip("/")
    return re.sub(r"/+", "/", clean)


@app.get("/getNotesList")
def get_notes_list():
    section = request.args.get("section") or "player"
    is_dm_user = require_dm()
    if section == "dm" and not is_dm_user:
        return jsonify({"error": "DM login required", "isDm": False}), 401
    notes_dir = DATA_DIR / "notes" / section
    notes_dir.mkdir(parents=True, exist_ok=True)

    folders = []
    root_files = []

    for entry in notes_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            files = [sub.stem for sub in entry.glob("*.md") if sub.is_file()]
            folders.append({"name": entry.name, "files": sorted(files)})
        elif entry.is_file() and entry.suffix == ".md":
            root_files.append(entry.stem)

    if not folders and not root_files:
        default_name = "Campaign_Overview" if section == "player" else "Welcome_DM_Notes"
        default_file = notes_dir / f"{default_name}.md"
        if not default_file.exists():
            content = f"# {default_name.replace('_', ' ')}\n\nWelcome to the {section.upper()} wiki!"
            default_file.write_text(content, encoding="utf-8")
        root_files = [default_name]

    return jsonify({
        "ok": True,
        "folders": sorted(folders, key=lambda f: f["name"]),
        "rootFiles": sorted(root_files),
        "section": section,
        "isDm": is_dm_user
    })


@app.post("/createWikiFolder")
def create_wiki_folder():
    if not require_dm():
        return jsonify({"error": "DM login required"}), 401
    data = json_body()
    section = data.get("section") or "player"
    name = safe_folder_name(data.get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    target = DATA_DIR / "notes" / section / name
    target.mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True})


@app.post("/deleteWikiFolder")
def delete_wiki_folder():
    if not require_dm():
        return jsonify({"error": "DM login required"}), 401
    data = json_body()
    section = data.get("section") or "player"
    name = safe_folder_name(data.get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    target = DATA_DIR / "notes" / section / name
    shutil.rmtree(target, ignore_errors=True)
    return jsonify({"ok": True})


@app.get("/loadNote")
def load_note():
    section = request.args.get("section") or "player"
    if section == "dm" and not require_dm():
        return "Unauthorized. DM login required.", 401
    raw_path = clean_wiki_path(request.args.get("name") or "")
    if not raw_path:
        raw_path = "Campaign_Overview" if section == "player" else "Welcome_DM_Notes"
    file = DATA_DIR / "notes" / section / f"{raw_path}.md"
    if not file.exists():
        return f"# {Path(raw_path).name.replace('_', ' ')}\n\nNew article text..."
    return file.read_text(encoding="utf-8")


@app.post("/saveNote")
def save_note():
    if not require_dm():
        return jsonify({"error": "DM login required to edit wiki notes"}), 401
    data = json_body()
    section = data.get("section") or "player"
    raw_path = clean_wiki_path(data.get("name") or "")
    if not raw_path:
        return jsonify({"error": "Invalid note name"}), 400
    text = data.get("text") or ""
    file = DATA_DIR / "notes" / section / f"{raw_path}.md"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return jsonify({"ok": True})


@app.post("/deleteNote")
def delete_note():
    if not require_dm():
        return jsonify({"error": "DM login required to delete wiki notes"}), 401
    data = json_body()
    section = data.get("section") or "player"
    raw_path = clean_wiki_path(data.get("name") or "")
    if raw_path:
        file = DATA_DIR / "notes" / section / f"{raw_path}.md"
        file.unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.post("/publishNote")
def publish_note():
    data = json_body()
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", data.get("name") or "")
    if not name:
        return jsonify({"error": "Invalid note name"}), 400
    source = DATA_DIR / "notes" / "dm" / f"{name}.md"
    dest_dir = DATA_DIR / "notes" / "player"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if source.exists():
        (dest_dir / f"{name}.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return jsonify({"ok": True, "message": f"Published '{name}' to Player Info wiki!"})
    return jsonify({"error": "Note not found"}), 404


def simple_markdown_render(text):
    import html as html_lib
    lines = text.splitlines()
    out = []
    in_code = False
    in_list = False
    in_table = False

    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue

        if in_code:
            out.append(html_lib.escape(line))
            continue

        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
            continue
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
            continue
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
            continue

        if line.startswith("> "):
            out.append(f"<blockquote>{line[2:]}</blockquote>")
            continue

        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{line[2:]}</li>")
            continue
        else:
            if in_list:
                out.append("</ul>")
                in_list = False

        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(c.replace("-", "").replace(":", "") == "" for c in cells):
                continue
            if not in_table:
                out.append("<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        else:
            if in_table:
                out.append("</tbody></table>")
                in_table = False

        if not line.strip():
            continue

        formatted = line
        formatted = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", formatted)
        formatted = re.sub(r"\*(.*?)\*", r"<em>\1</em>", formatted)
        formatted = re.sub(r"`(.*?)`", r"<code>\1</code>", formatted)
        out.append(f"<p>{formatted}</p>")

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</tbody></table>")
    if in_code:
        out.append("</code></pre>")

    return "\n".join(out)


@app.post("/renderMarkdown")
def render_markdown():
    data = json_body()
    text = data.get("text") or ""
    def repl_wiki(m):
        link_text = m.group(1).strip()
        return f'<a class="wiki-link" href="#" onclick="event.preventDefault(); loadDoc(\'{link_text}\')"><i class="fa-solid fa-link"></i> {link_text}</a>'
    processed = re.sub(r"\[\[(.*?)\]\]", repl_wiki, text)
    html = simple_markdown_render(processed)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.post("/createScene")
def create_scene():
    if not require_dm():
        return redirect("/dm-login")
    data = json_body()
    scene_id = now_ms()
    scene = {"sceneId": scene_id, "sceneName": data.get("sceneName"), "tokens": []}
    scene_store.save_scene(scene)
    scene_store.add_scene(scene)
    return jsonify({"sceneId": scene_id})


@app.get("/scenes")
def get_scenes():
    return jsonify({"scenes": scene_store.get_all_scenes()})


@app.post("/updateScene")
def update_scene():
    if not require_dm():
        return redirect("/dm-login")
    try:
        scene_store.update_scene(json_body().get("scene"))
        return jsonify({"message": "Scene updated."})
    except Exception:
        return "Error updating scene.", 500


@app.post("/deleteScene")
def delete_scene():
    if not require_dm():
        return redirect("/dm-login")
    try:
        scene_id = json_body().get("sceneId")
        scene_store.delete_scene(scene_id)
        socketio.emit("sceneDeleted", {"sceneId": scene_id})
        return jsonify({"success": True})
    except Exception:
        return jsonify({"success": False, "message": "Error deleting scene."}), 500


@app.post("/duplicateScene")
def duplicate_scene():
    if not require_dm():
        return redirect("/dm-login")
    data = json_body()
    try:
        source = scene_store.load_scene(data.get("sceneId"))
        new_scene = json.loads(json.dumps(source))
        new_scene_id = now_ms()
        new_scene["sceneId"] = new_scene_id
        new_scene["sceneName"] = data.get("sceneName") or f"Copy of {source.get('sceneName')}"
        scene_store.save_scene(new_scene)
        scene_store.add_scene(new_scene)
        return jsonify({"sceneId": new_scene_id})
    except Exception:
        return jsonify({"error": "Error duplicating scene."}), 500


@app.post("/updateSceneOrder")
def update_scene_order():
    if not require_dm():
        return redirect("/dm-login")
    try:
        scene_store.update_scene_order(json_body().get("sceneOrder") or [])
        return jsonify({"success": True})
    except Exception:
        return jsonify({"success": False, "message": "Failed to update scene order"})


@app.post("/upload")
def upload_file():
    if not require_dm():
        return redirect("/dm-login")
    file = request.files.get("file")
    if not file:
        return "No file uploaded.", 400
    mime_type = file.mimetype or mimetypes.guess_type(file.filename)[0] or ""
    if mime_type.startswith("video/"):
        media_type = "video"
    elif mime_type.startswith("image/"):
        media_type = "image"
    else:
        return "Unsupported file type.", 400
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{now_ms()}-{secure_filename(file.filename)}"
    file.save(UPLOADS_DIR / filename)
    return jsonify({"imageUrl": f"/uploads/{filename}", "mediaType": media_type})


@app.post("/uploadMusic")
def upload_music():
    if not require_dm():
        return redirect("/dm-login")
    file = request.files.get("music")
    if not file:
        return jsonify({"success": False, "message": "No music file uploaded."}), 400
    mime_type = file.mimetype or ""
    if not mime_type.startswith("audio/"):
        return jsonify({"success": False, "message": "Unsupported file type"}), 400
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{now_ms()}-{secure_filename(file.filename)}"
    file.save(MUSIC_DIR / filename)
    return jsonify({"success": True, "musicUrl": f"/music/{filename}", "filename": filename})


@app.get("/musicList")
def music_list():
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    tracks = []
    for path in MUSIC_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in MUSIC_EXTS:
            tracks.append({
                "name": re.sub(r"^\d+\s*[-_]?\s*", "", path.name),
                "filename": path.name,
                "url": f"/music/{path.name}",
            })
    return jsonify({"success": True, "musicTracks": tracks})


@app.post("/deleteMusic")
def delete_music():
    if not require_dm():
        return redirect("/dm-login")
    filename = Path(json_body().get("filename") or "").name
    if not filename:
        return jsonify({"success": False, "message": "No filename provided."}), 400
    path = MUSIC_DIR / filename
    if not path.exists():
        return jsonify({"success": False, "message": "File not found."}), 404
    path.unlink()
    return jsonify({"success": True})


@app.get("/mediaList")
def media_list():
    if not require_player():
        return redirect("/player-login")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    folders = []
    root_files = []
    for entry in MEDIA_DIR.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            files = []
            for sub in entry.iterdir():
                media_type = get_media_type(sub.name)
                if sub.is_file() and not sub.name.startswith(".") and media_type:
                    files.append({"name": sub.name, "url": f"/media/{entry.name}/{sub.name}", "mediaType": media_type})
            folders.append({"name": entry.name, "files": files})
        elif entry.is_file():
            media_type = get_media_type(entry.name)
            if media_type:
                root_files.append({"name": entry.name, "url": f"/media/{entry.name}", "mediaType": media_type})
    return jsonify({"folders": folders, "rootFiles": root_files})


@app.post("/mediaFolder")
def media_folder_create():
    if not require_dm():
        return redirect("/dm-login")
    name = safe_folder_name(json_body().get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    (MEDIA_DIR / name).mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True})


@app.post("/mediaUpload")
def media_upload():
    if not require_dm():
        return redirect("/dm-login")
    folder = safe_folder_name(request.args.get("folder"))
    dest = MEDIA_DIR / folder if folder else MEDIA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files")
    for file in files:
        ext = Path(file.filename).suffix.lower()
        mime_type = file.mimetype or ""
        allowed = (
            mime_type.startswith("image/")
            or mime_type.startswith("video/")
            or mime_type == "application/pdf"
            or mime_type.startswith("text/")
            or ext in MEDIA_EXTS
        )
        if allowed:
            file.save(dest / secure_filename(file.filename))
    return jsonify({"ok": True, "count": len(files)})


@app.get("/playerMediaList")
def player_media_list():
    if not require_player():
        return redirect("/player-login")
    PLAYER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    folders = []
    root_files = []
    for entry in PLAYER_MEDIA_DIR.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            files = []
            for sub in entry.iterdir():
                media_type = get_media_type(sub.name)
                if sub.is_file() and not sub.name.startswith(".") and media_type:
                    files.append({"name": sub.name, "url": f"/player-media/{entry.name}/{sub.name}", "mediaType": media_type})
            folders.append({"name": entry.name, "files": files})
        elif entry.is_file():
            media_type = get_media_type(entry.name)
            if media_type:
                root_files.append({"name": entry.name, "url": f"/player-media/{entry.name}", "mediaType": media_type})
    return jsonify({"folders": folders, "rootFiles": root_files})


@app.post("/playerMediaUpload")
def player_media_upload():
    if not require_player():
        return redirect("/player-login")
    provided = request.headers.get("X-DM-Password") or ""
    if provided != app.config["DM_PASSWORD"]:
        return jsonify({"error": "Invalid DM password."}), 403
    folder = safe_folder_name(request.args.get("folder"))
    dest = PLAYER_MEDIA_DIR / folder if folder else PLAYER_MEDIA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files")
    for file in files:
        ext = Path(file.filename).suffix.lower()
        mime_type = file.mimetype or ""
        allowed = (
            mime_type.startswith("image/")
            or mime_type.startswith("video/")
            or mime_type == "application/pdf"
            or mime_type.startswith("text/")
            or ext in MEDIA_EXTS
        )
        if allowed:
            file.save(dest / secure_filename(file.filename))
    return jsonify({"ok": True, "count": len(files)})


@app.post("/playerMediaFolder")
def player_media_folder_create():
    if not require_player():
        return redirect("/player-login")
    provided = request.headers.get("X-DM-Password") or ""
    if provided != app.config["DM_PASSWORD"]:
        return jsonify({"error": "Invalid DM password."}), 403
    name = safe_folder_name(json_body().get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    (PLAYER_MEDIA_DIR / name).mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True})


@app.delete("/playerMediaFolder")
def player_media_folder_delete():
    if not require_player():
        return redirect("/player-login")
    provided = request.headers.get("X-DM-Password") or ""
    if provided != app.config["DM_PASSWORD"]:
        return jsonify({"error": "Invalid DM password."}), 403
    name = safe_folder_name(json_body().get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    shutil.rmtree(PLAYER_MEDIA_DIR / name, ignore_errors=True)
    return jsonify({"ok": True})


@app.delete("/playerMediaFile")
def player_media_file_delete():
    if not require_player():
        return redirect("/player-login")
    provided = request.headers.get("X-DM-Password") or ""
    if provided != app.config["DM_PASSWORD"]:
        return jsonify({"error": "Invalid DM password."}), 403
    rel = safe_relative_player_media_path(json_body().get("url"))
    if not rel:
        return jsonify({"error": "Bad path"}), 400
    try:
        (PLAYER_MEDIA_DIR / rel).unlink()
    except OSError:
        return jsonify({"error": "File not found."}), 404
    return jsonify({"ok": True})


@app.delete("/mediaFolder")
def media_folder_delete():
    if not require_dm():
        return redirect("/dm-login")
    name = safe_folder_name(json_body().get("name"))
    if not name:
        return jsonify({"error": "Invalid folder name"}), 400
    shutil.rmtree(MEDIA_DIR / name, ignore_errors=True)
    return jsonify({"ok": True})


@app.patch("/mediaFolder")
def media_folder_rename():
    if not require_dm():
        return redirect("/dm-login")
    data = json_body()
    old_name = safe_folder_name(data.get("oldName"))
    new_name = safe_folder_name(data.get("newName"))
    if not old_name or not new_name:
        return jsonify({"error": "Invalid folder name"}), 400
    (MEDIA_DIR / old_name).rename(MEDIA_DIR / new_name)
    return jsonify({"ok": True})


@app.delete("/mediaFile")
def media_file_delete():
    if not require_dm():
        return redirect("/dm-login")
    rel = safe_relative_media_path(json_body().get("url"))
    if not rel:
        return jsonify({"error": "Bad path"}), 400
    (MEDIA_DIR / rel).unlink()
    return jsonify({"ok": True})


@app.get("/passwords")
def passwords_get():
    if not require_dm():
        return redirect("/dm-login")
    current = read_secrets()
    return jsonify({
        "dmPassword": current.get("DM_PASSWORD") or DEFAULT_SECRETS["DM_PASSWORD"],
        "playerPassword": current.get("PLAYER_PASSWORD") or DEFAULT_SECRETS["PLAYER_PASSWORD"],
    })


@app.put("/passwords")
def passwords_put():
    if not require_dm():
        return redirect("/dm-login")
    data = json_body()
    dm_password = str(data.get("dmPassword") or "").strip()
    player_password = str(data.get("playerPassword") or "").strip()
    if not dm_password or not player_password:
        return jsonify({"error": "Both passwords are required."}), 400
    updated = {"DM_PASSWORD": dm_password, "PLAYER_PASSWORD": player_password}
    ensure_secret_storage()
    SECRET_FILE.write_text(format_secrets(updated), encoding="utf-8")
    app.config["DM_PASSWORD"] = dm_password
    app.config["PLAYER_PASSWORD"] = player_password
    return jsonify({"ok": True})


@app.get("/sticky-notes")
def sticky_notes_get():
    if not require_dm():
        return redirect("/dm-login")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not NOTES_FILE.exists():
        NOTES_FILE.write_text("[]", encoding="utf-8")
    return jsonify(json.loads(NOTES_FILE.read_text(encoding="utf-8")))


@app.post("/sticky-notes")
def sticky_notes_post():
    if not require_dm():
        return redirect("/dm-login")
    notes = request.get_json(silent=True)
    if not isinstance(notes, list):
        return jsonify({"error": "Expected array"}), 400
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes), encoding="utf-8")
    return jsonify({"ok": True})


def server_roll(raw_notation):
    if not isinstance(raw_notation, str):
        return {"notation": "1d6", "text": "?", "color": "#4CAF50"}
    clean = raw_notation.strip()
    match = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", clean, re.I)
    if not match:
        return {"notation": clean, "text": clean, "color": "#4CAF50"}
    qty = min(int(match.group(1)), 20)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    rolls = [random.randint(1, sides) for _ in range(qty)]
    total = sum(rolls) + modifier
    mod_str = f"+{modifier}" if modifier > 0 else str(modifier) if modifier < 0 else ""
    return {
        "notation": f"{qty}d{sides}@{','.join(str(r) for r in rolls)}",
        "text": f"{qty}d{sides}{mod_str} = {total}",
        "color": "#4CAF50",
    }


def is_dm_socket():
    return getattr(request, "sid", None) and socket_roles.get(request.sid) == "dm"


socket_roles = {}


@socketio.on("connect")
def socket_connect():
    role = request.args.get("role") or "player"
    socket_roles[request.sid] = role
    join_room(role)
    emit("activeSceneId", scene_store.active_scene_id)
    if bg_color:
        emit("setBgColor", {"color": bg_color})
    if grid_state is not None:
        emit("toggleGrid", grid_state)
    if initiative_state:
        emit("updateInitiative", initiative_state)


@socketio.on("disconnect")
def socket_disconnect():
    socket_roles.pop(request.sid, None)


@socketio.on("loadScene")
def socket_load_scene(data):
    try:
        scene = scene_store.load_scene((data or {}).get("sceneId"))
        if socket_roles.get(request.sid) == "player":
            filtered = dict(scene)
            filtered["tokens"] = [token for token in scene.get("tokens", []) if not token.get("hidden")]
            emit("sceneData", filtered)
        else:
            emit("sceneData", scene)
    except Exception:
        emit("error", {"message": "Failed to load scene."})


@socketio.on("changeScene")
def socket_change_scene(data):
    if not is_dm_socket():
        return
    scene_store.change_active_scene((data or {}).get("sceneId"))
    socketio.emit("activeSceneId", scene_store.active_scene_id)


@socketio.on("updateToken")
def socket_update_token(data):
    scene_id = (data or {}).get("sceneId")
    token_id = (data or {}).get("tokenId")
    properties = (data or {}).get("properties") or {}
    if not scene_id or not token_id:
        return
    if not is_dm_socket():
        scene = scene_store.scenes.get(scene_id)
        token = next((t for t in (scene or {}).get("tokens", []) if t.get("tokenId") == token_id), None)
        allowed = all(key in {"x", "y"} for key in properties.keys())
        if not token or not token.get("movableByPlayers") or not allowed:
            return
    token, was_hidden, is_hidden = scene_store.update_token(scene_id, token_id, properties)
    if not token:
        return
    if was_hidden != is_hidden:
        if is_hidden:
            emit("removeToken", {"sceneId": scene_id, "tokenId": token_id}, to="player", include_self=False)
            emit("updateToken", {"sceneId": scene_id, "tokenId": token_id, "properties": properties}, to="dm", include_self=False)
        else:
            emit("addToken", {"sceneId": scene_id, "token": token}, to="player", include_self=False)
            emit("updateToken", {"sceneId": scene_id, "tokenId": token_id, "properties": properties}, to="dm", include_self=False)
    elif is_hidden:
        emit("updateToken", {"sceneId": scene_id, "tokenId": token_id, "properties": properties}, to="dm", include_self=False)
    else:
        emit("updateToken", {"sceneId": scene_id, "tokenId": token_id, "properties": properties}, broadcast=True, include_self=False)


@socketio.on("addToken")
def socket_add_token(data):
    if not is_dm_socket():
        return
    scene_id = (data or {}).get("sceneId")
    token = (data or {}).get("token")
    scene_store.add_token(scene_id, token)
    socketio.emit("addToken", {"sceneId": scene_id, "token": token})


@socketio.on("removeToken")
def socket_remove_token(data):
    if not is_dm_socket():
        return
    scene_id = (data or {}).get("sceneId")
    token_id = (data or {}).get("tokenId")
    if scene_store.remove_token(scene_id, token_id):
        socketio.emit("removeToken", {"sceneId": scene_id, "tokenId": token_id})


@socketio.on("playTrack")
def socket_play_track(data):
    if is_dm_socket():
        emit("playTrack", data, broadcast=True, include_self=False)


@socketio.on("pauseTrack")
def socket_pause_track(data):
    if is_dm_socket():
        emit("pauseTrack", data, broadcast=True, include_self=False)


@socketio.on("setTrackVolume")
def socket_track_volume(data):
    if is_dm_socket():
        emit("setTrackVolume", data, broadcast=True, include_self=False)


@socketio.on("deleteTrack")
def socket_delete_track(data):
    if is_dm_socket():
        emit("deleteTrack", data, broadcast=True, include_self=False)


@socketio.on("addTrack")
def socket_add_track(data):
    if is_dm_socket():
        emit("addTrack", data, broadcast=True, include_self=False)


@socketio.on("updateInitiative")
def socket_update_initiative(data):
    global initiative_state
    if not is_dm_socket():
        return
    initiative_state = data
    socketio.emit("updateInitiative", data)


@socketio.on("toggleGrid")
def socket_toggle_grid(data):
    global grid_state
    if not is_dm_socket():
        return
    grid_state = data
    emit("toggleGrid", data, to="player", include_self=False)


@socketio.on("snapView")
def socket_snap_view(data):
    if not is_dm_socket():
        return
    if data and data.get("sceneId"):
        scene_store.change_active_scene(data.get("sceneId"))
    emit("snapView", data, to="player", include_self=False)


@socketio.on("setBgColor")
def socket_set_bg_color(data):
    global bg_color
    if not is_dm_socket():
        return
    bg_color = (data or {}).get("color")
    emit("setBgColor", data, to="player", include_self=False)


@socketio.on("pingScene")
def socket_ping_scene(data):
    emit("pingScene", data, broadcast=True, include_self=False)


@socketio.on("rollDice")
def socket_roll_dice(payload):
    raw_notation = payload if isinstance(payload, str) else (payload or {}).get("notation")
    colorset = (payload or {}).get("colorset", "white") if isinstance(payload, dict) else "white"
    texture = (payload or {}).get("texture", "") if isinstance(payload, dict) else ""
    result = server_roll(raw_notation)
    socketio.emit("diceRolled", {"notation": result["notation"], "colorset": colorset, "texture": texture})
    socketio.emit("diceResult", {"text": result["text"], "color": result["color"]})


@socketio.on("clearDice")
def socket_clear_dice():
    socketio.emit("diceCleared")


@socketio.on("addTokenFromLibrary")
def socket_add_token_from_library(data):
    if not is_dm_socket() or not scene_store.active_scene_id:
        return
    scene = scene_store.scenes.get(scene_store.active_scene_id) or scene_store.load_scene(scene_store.active_scene_id)
    max_z = max([token.get("zIndex", 0) for token in scene.get("tokens", [])] or [0])
    token = {
        "tokenId": f"{now_ms()}-{random.random():.9f}".replace("0.", ""),
        "sceneId": scene_store.active_scene_id,
        "imageUrl": (data or {}).get("imageUrl"),
        "mediaType": (data or {}).get("mediaType") or "image",
        "x": 100,
        "y": 100,
        "width": (data or {}).get("width") or 100,
        "height": (data or {}).get("height") or 100,
        "rotation": 0,
        "zIndex": max_z + 1,
        "movableByPlayers": False,
        "hidden": False,
    }
    scene_store.add_token(scene_store.active_scene_id, token)
    socketio.emit("addToken", {"sceneId": scene_store.active_scene_id, "token": token})


def main():
    port = int(os.environ.get("VTT_PORT", "3000"))
    print(f"Passwords loaded from: {SECRET_FILE}")
    print(f"Project folder: {BASE_DIR}")
    print(f"Public folder: {PUBLIC_DIR}")
    print(f"DM Password: {app.config['DM_PASSWORD']}")
    print(f"Player Password: {app.config['PLAYER_PASSWORD']}")
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
