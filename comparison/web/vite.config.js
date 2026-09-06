import { defineConfig } from 'vite';
import { cpSync, existsSync, createReadStream, statSync } from 'node:fs';
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const cesiumPath = resolve(root, 'node_modules/cesium/Build/Cesium');
// Serve Cesium workers/assets locally in development and copy them on build.
function cesiumAssets() {
  return {
    name: 'local-cesium-assets',
    configureServer(server) {
      server.middlewares.use('/scene-assets', (req, res, next) => {
        if ((req.url || '').split('?')[0] !== '/civic-center.glb') { next(); return; }
        const asset = resolve(root, '../shared/civic-center.glb');
        if (!existsSync(asset)) { res.statusCode = 404; res.end('Build the shared Blender asset first.'); return; }
        res.setHeader('Content-Type', 'model/gltf-binary');
        createReadStream(asset).pipe(res);
      });
      server.middlewares.use('/cesium', (req, res, next) => {
        let path;
        try { path = resolve(cesiumPath, `.${decodeURIComponent((req.url || '/').split('?')[0])}`); } catch { next(); return; }
        if (!path.startsWith(cesiumPath + sep) || !existsSync(path) || !statSync(path).isFile()) { next(); return; }
        const types = { '.js': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.png': 'image/png', '.svg': 'image/svg+xml', '.css': 'text/css' };
        const extension = path.slice(path.lastIndexOf('.'));
        if (types[extension]) res.setHeader('Content-Type', types[extension]);
        createReadStream(path).pipe(res);
      });
    },
    closeBundle() {
      cpSync(resolve(root, '../shared/civic-center.glb'), resolve(root, 'dist/scene-assets/civic-center.glb'));
      for (const dir of ['Assets', 'Workers', 'ThirdParty', 'Widgets']) {
        cpSync(resolve(cesiumPath, dir), resolve(root, 'dist/cesium', dir), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  root,
  define: { CESIUM_BASE_URL: JSON.stringify('/cesium') },
  plugins: [cesiumAssets()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, fs: { allow: [resolve(root, '..')] } },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: { chunkSizeWarningLimit: 3000 },
});
