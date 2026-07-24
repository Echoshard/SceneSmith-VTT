// middlewares/multerSFX.js
const multer = require('multer');
const fs = require('fs');

const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    let uploadPath = 'public/sfx/';
    fs.mkdirSync(uploadPath, { recursive: true });
    cb(null, uploadPath);
  },
  filename: function (req, file, cb) {
    cb(null, Date.now() + '-' + file.originalname);
  }
});

const uploadSFX = multer({
  storage: storage,
  fileFilter: function (req, file, cb) {
    const mimeType = file.mimetype;
    if (mimeType.startsWith('audio/')) {
      cb(null, true);
    } else {
      cb(new Error('Unsupported audio file type'));
    }
  },
});

module.exports = uploadSFX;
