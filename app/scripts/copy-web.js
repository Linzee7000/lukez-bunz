// Copies the web app (index.html, icons, data/) from the repo root into app/www.
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..', '..');
const out = path.join(__dirname, '..', 'www');
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const f of fs.readdirSync(root)) {
  if (f === 'index.html' || f.endsWith('.png')) fs.copyFileSync(path.join(root, f), path.join(out, f));
}
fs.cpSync(path.join(root, 'data'), path.join(out, 'data'), { recursive: true });
console.log('Copied web app into', out);
