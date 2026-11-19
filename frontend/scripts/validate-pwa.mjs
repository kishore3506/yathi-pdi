import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const dist = resolve('dist');
const manifest = JSON.parse(readFileSync(resolve(dist, 'manifest.webmanifest'), 'utf8'));

assert.equal(manifest.display, 'standalone');
assert.ok(manifest.name);
assert.ok(manifest.short_name);
assert.ok(manifest.theme_color);

for (const size of [192, 512]) {
  const icon = manifest.icons.find(entry => entry.sizes === `${size}x${size}`);
  assert.ok(icon, `Missing ${size}x${size} icon`);
  const image = readFileSync(resolve(dist, icon.src.slice(1)));
  assert.equal(image.toString('hex', 0, 8), '89504e470d0a1a0a', `${icon.src} is not PNG`);
  assert.equal(image.readUInt32BE(16), size, `${icon.src} has the wrong width`);
  assert.equal(image.readUInt32BE(20), size, `${icon.src} has the wrong height`);
}

assert.ok(manifest.icons.some(icon => icon.purpose?.split(/\s+/).includes('maskable')));
const serviceWorkerPath = resolve(dist, 'sw.js');
assert.ok(existsSync(serviceWorkerPath), 'Missing service worker');
const serviceWorker = readFileSync(serviceWorkerPath, 'utf8');
assert.ok(serviceWorker.includes("startsWith('/api/')"), 'Service worker must exclude API routes');
assert.ok(!serviceWorker.includes('__PDI_RELEASE_ID__'), 'Service worker release ID was not injected');
assert.ok(serviceWorker.includes('yathi-pdi-static-'), 'Service worker cache must be release-specific');

console.log('PWA manifest, PNG icons, and release-specific API-excluding service worker are valid.');
