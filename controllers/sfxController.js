// controllers/sfxController.js
const uploadSFX = require('../middlewares/multerSFX');
const path = require('path');
const fs = require('fs');

exports.uploadSFX = (req, res) => {
  uploadSFX.single('sfx')(req, res, (err) => {
    if (err) {
      console.error('SFX upload error:', err);
      return res.status(400).json({ success: false, message: err.message });
    }
    if (!req.file) {
      return res.status(400).json({ success: false, message: 'No SFX audio file uploaded.' });
    }

    console.log(`SFX uploaded: ${req.file.filename}`);

    res.json({
      success: true,
      sfxUrl: `/sfx/${req.file.filename}`,
      filename: req.file.filename
    });
  });
};

exports.getSFXList = (req, res) => {
  const sfxDir = path.join(__dirname, '..', 'public', 'sfx');
  if (!fs.existsSync(sfxDir)) {
    fs.mkdirSync(sfxDir, { recursive: true });
  }
  fs.readdir(sfxDir, (err, files) => {
    if (err) {
      console.error('Error reading SFX directory:', err);
      return res.status(500).json({ success: false, message: 'Error reading SFX directory.' });
    }
    const sfxFiles = files.filter(file => {
      return (
        file.endsWith('.mp3') ||
        file.endsWith('.wav') ||
        file.endsWith('.ogg') ||
        file.endsWith('.m4a') ||
        file.endsWith('.flac')
      );
    });
    const sfxTracks = sfxFiles.map(file => {
      return {
        name: file.replace(/^\d+\s*[-_]?\s*/, ''),
        filename: file,
        url: '/sfx/' + file
      };
    });
    res.json({ success: true, sfxTracks });
  });
};

exports.deleteSFX = (req, res) => {
  const { filename } = req.body;
  if (!filename) {
    return res.status(400).json({ success: false, message: 'No filename provided.' });
  }
  const sfxDir = path.join(__dirname, '..', 'public', 'sfx');
  const safeFilename = path.basename(filename);
  const filePath = path.join(sfxDir, safeFilename);
  fs.access(filePath, fs.constants.F_OK, (err) => {
    if (err) {
      console.error('SFX file does not exist:', filePath);
      return res.status(404).json({ success: false, message: 'File not found.' });
    }
    fs.unlink(filePath, (err) => {
      if (err) {
        console.error('Error deleting SFX file:', err);
        return res.status(500).json({ success: false, message: 'Error deleting file.' });
      }
      console.log('Deleted SFX file:', filePath);
      res.json({ success: true });
    });
  });
};
