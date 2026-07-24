// routes.js
const express = require('express');
const router = express.Router();
const path = require('path');
const fs = require('fs');
const fsPromises = require('fs').promises;

const MEDIA_DIR = path.join(__dirname, 'public', 'media');
const SECRET_DIR = path.join(__dirname, 'data', 'private');
const SECRET_FILE = path.join(SECRET_DIR, 'secrets.txt');
const LEGACY_SECRET_FILE = path.join(__dirname, 'secret.txt');
const DEFAULT_SECRETS = {
  DM_PASSWORD: 'CODE',
  PLAYER_PASSWORD: 'PLAY',
};
const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']);
const VIDEO_EXTS = new Set(['.mp4', '.webm', '.ogv', '.mov']);
const PDF_EXTS = new Set(['.pdf']);
const TEXT_EXTS = new Set(['.txt', '.md', '.json', '.csv', '.log']);
const DOC_EXTS = new Set([...PDF_EXTS, ...TEXT_EXTS]);
const MEDIA_EXTS = new Set([...IMAGE_EXTS, ...VIDEO_EXTS, ...DOC_EXTS]);

// Controllers
const sceneController = require('./controllers/sceneController');
const uploadController = require('./controllers/uploadController');
const musicController = require('./controllers/musicController');
const sfxController = require('./controllers/sfxController');
const stickyNotesController = require('./controllers/stickyNotesController');

// Middleware to check if user is authenticated as DM
function checkDMAuth(req, res, next) {
  if (req.session && req.session.isDM) {
    next();
  } else {
    res.redirect('/dm-login');
  }
}

function checkPlayerAuth(req, res, next) {
  if (req.session && (req.session.isPlayer || req.session.isDM)) {
    next();
  } else {
    res.redirect('/player-login');
  }
}

function parseSecrets(raw) {
  const trimmed = raw.trim();
  if (!trimmed.includes('=')) {
    return { ...DEFAULT_SECRETS, DM_PASSWORD: trimmed || DEFAULT_SECRETS.DM_PASSWORD };
  }

  return raw.split(/\r?\n/).reduce((secrets, line) => {
    const clean = line.trim();
    if (!clean || clean.startsWith('#')) return secrets;

    const eq = clean.indexOf('=');
    if (eq === -1) return secrets;

    const key = clean.slice(0, eq).trim();
    const value = clean.slice(eq + 1).trim();
    if (key) secrets[key] = value;
    return secrets;
  }, { ...DEFAULT_SECRETS });
}

function formatSecrets(secrets) {
  return [
    '# Passwords can be edited here or from the Media Library password tab.',
    '# These values stay server-side and are never sent to browser JavaScript.',
    `DM_PASSWORD=${secrets.DM_PASSWORD || DEFAULT_SECRETS.DM_PASSWORD}`,
    `PLAYER_PASSWORD=${secrets.PLAYER_PASSWORD || DEFAULT_SECRETS.PLAYER_PASSWORD}`,
    '',
  ].join('\n');
}

async function ensureSecretStorage() {
  await fsPromises.mkdir(SECRET_DIR, { recursive: true });

  if (!fs.existsSync(SECRET_FILE) && fs.existsSync(LEGACY_SECRET_FILE)) {
    try {
      await fsPromises.rename(LEGACY_SECRET_FILE, SECRET_FILE);
    } catch {
      await fsPromises.copyFile(LEGACY_SECRET_FILE, SECRET_FILE);
      await fsPromises.unlink(LEGACY_SECRET_FILE);
    }
  }
}

async function readSecretsFile() {
  await ensureSecretStorage();
  try {
    return parseSecrets(await fsPromises.readFile(SECRET_FILE, 'utf8'));
  } catch {
    const secrets = { ...DEFAULT_SECRETS };
    await fsPromises.writeFile(SECRET_FILE, formatSecrets(secrets), 'utf8');
    return secrets;
  }
}

function getMediaType(name) {
  const ext = path.extname(name).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (VIDEO_EXTS.has(ext)) return 'video';
  if (PDF_EXTS.has(ext)) return 'pdf';
  if (TEXT_EXTS.has(ext)) return 'text';
  return null;
}

router.get('/', checkPlayerAuth, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

router.get('/player-login', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'player-login.html'));
});

router.post('/player-login', (req, res) => {
  const password = req.body.password;
  if (password === req.app.locals.playerPassword) {
    req.session.isPlayer = true;
    res.redirect('/');
  } else {
    res.send('Incorrect password. <a href="/player-login">Try again</a>');
  }
});

// Route for DM login form
router.get('/dm-login', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dm-login.html'));
});

// Handle DM login
router.post('/dm-login', (req, res) => {
  const password = req.body.password;
  if (password === req.app.locals.dmPassword) {
    req.session.isDM = true;
    res.redirect('/dm');
  } else {
    res.send('Incorrect password. <a href="/dm-login">Try again</a>');
  }
});

// Route for DM interface, protected
router.get('/dm', checkDMAuth, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dm.html'));
});

// Protect other DM-specific routes
// Scene Routes
router.post('/createScene', checkDMAuth, sceneController.createScene);
router.post('/duplicateScene', checkDMAuth, sceneController.duplicateScene);
router.get('/scenes', sceneController.getScenes); // Players can view scenes
router.post('/updateScene', checkDMAuth, sceneController.updateScene);
router.post('/deleteScene', checkDMAuth, sceneController.deleteScene);
router.post('/updateSceneOrder', checkDMAuth, sceneController.updateSceneOrder);

// Upload Routes
router.post('/upload', checkDMAuth, uploadController.uploadFile);

// Media Library Routes
router.get('/files', checkDMAuth, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'files.html'));
});

router.get('/mediaList', checkDMAuth, async (req, res) => {
  try {
    if (!fs.existsSync(MEDIA_DIR)) fs.mkdirSync(MEDIA_DIR, { recursive: true });
    const entries = await fsPromises.readdir(MEDIA_DIR, { withFileTypes: true });
    const folders = [];
    const rootFiles = [];
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      if (entry.isDirectory()) {
        const sub = await fsPromises.readdir(path.join(MEDIA_DIR, entry.name), { withFileTypes: true });
        const files = sub
          .filter(e => e.isFile() && !e.name.startsWith('.') && getMediaType(e.name))
          .map(e => ({ name: e.name, url: `/media/${entry.name}/${e.name}`, mediaType: getMediaType(e.name) }));
        folders.push({ name: entry.name, files });
      } else if (entry.isFile() && getMediaType(entry.name)) {
        rootFiles.push({ name: entry.name, url: `/media/${entry.name}`, mediaType: getMediaType(entry.name) });
      }
    }
    res.json({ folders, rootFiles });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/mediaFolder', checkDMAuth, (req, res) => {
  const name = (req.body.name || '').replace(/[^a-zA-Z0-9_\- ]/g, '').trim();
  if (!name) return res.status(400).json({ error: 'Invalid folder name' });
  const target = path.join(MEDIA_DIR, name);
  try {
    fs.mkdirSync(target, { recursive: true });
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const multerMedia = require('multer')({
  storage: require('multer').diskStorage({
    destination(req, file, cb) {
      const folder = (req.query.folder || '').replace(/[^a-zA-Z0-9_\- ]/g, '').trim();
      const dest = folder ? path.join(MEDIA_DIR, folder) : MEDIA_DIR;
      fs.mkdirSync(dest, { recursive: true });
      cb(null, dest);
    },
    filename(req, file, cb) { cb(null, file.originalname); },
  }),
  fileFilter(req, file, cb) {
    const ext = path.extname(file.originalname).toLowerCase();
    const allowedMime =
      file.mimetype.startsWith('image/') ||
      file.mimetype.startsWith('video/') ||
      file.mimetype === 'application/pdf' ||
      file.mimetype.startsWith('text/');
    cb(null, allowedMime || MEDIA_EXTS.has(ext));
  },
});
router.post('/mediaUpload', checkDMAuth, multerMedia.array('files'), (req, res) => {
  res.json({ ok: true, count: req.files.length });
});

router.delete('/mediaFolder', checkDMAuth, async (req, res) => {
  const name = (req.body.name || '').replace(/[^a-zA-Z0-9_\- ]/g, '').trim();
  if (!name) return res.status(400).json({ error: 'Invalid folder name' });
  const target = path.join(MEDIA_DIR, name);
  try {
    await fsPromises.rm(target, { recursive: true, force: true });
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.patch('/mediaFolder', checkDMAuth, async (req, res) => {
  const oldName = (req.body.oldName || '').replace(/[^a-zA-Z0-9_\- ]/g, '').trim();
  const newName = (req.body.newName || '').replace(/[^a-zA-Z0-9_\- ]/g, '').trim();
  if (!oldName || !newName) return res.status(400).json({ error: 'Invalid folder name' });
  try {
    await fsPromises.rename(path.join(MEDIA_DIR, oldName), path.join(MEDIA_DIR, newName));
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.delete('/mediaFile', checkDMAuth, async (req, res) => {
  const rel = (req.body.url || '').replace(/^\/media\//, '');
  if (!rel || rel.includes('..')) return res.status(400).json({ error: 'Bad path' });
  const target = path.join(MEDIA_DIR, rel);
  try {
    await fsPromises.unlink(target);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.get('/passwords', checkDMAuth, async (req, res) => {
  try {
    const secrets = await readSecretsFile();
    res.json({
      dmPassword: secrets.DM_PASSWORD || DEFAULT_SECRETS.DM_PASSWORD,
      playerPassword: secrets.PLAYER_PASSWORD || DEFAULT_SECRETS.PLAYER_PASSWORD,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.put('/passwords', checkDMAuth, async (req, res) => {
  const dmPassword = String(req.body.dmPassword || '').trim();
  const playerPassword = String(req.body.playerPassword || '').trim();
  if (!dmPassword || !playerPassword) {
    return res.status(400).json({ error: 'Both passwords are required.' });
  }

  try {
    await ensureSecretStorage();
    const secrets = {
      DM_PASSWORD: dmPassword,
      PLAYER_PASSWORD: playerPassword,
    };
    await fsPromises.writeFile(SECRET_FILE, formatSecrets(secrets), 'utf8');
    req.app.locals.dmPassword = dmPassword;
    req.app.locals.playerPassword = playerPassword;
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Music & SFX Routes
router.post('/uploadMusic', checkDMAuth, musicController.uploadMusic);
router.get('/musicList', musicController.getMusicList); // Players can get music list
router.post('/deleteMusic', checkDMAuth, musicController.deleteMusic);

router.post('/uploadSFX', checkDMAuth, sfxController.uploadSFX);
router.get('/sfxList', sfxController.getSFXList);
router.post('/deleteSFX', checkDMAuth, sfxController.deleteSFX);

// App Pages
router.get('/tavern-music', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'tavern-music.html'));
});

router.get('/imageconverter', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'imageconverter', 'index.html'));
});

// Sticky Notes Routes (DM only)
router.get('/sticky-notes',  checkDMAuth, stickyNotesController.getNotes);
router.post('/sticky-notes', checkDMAuth, stickyNotesController.saveNotes);

module.exports = router;
