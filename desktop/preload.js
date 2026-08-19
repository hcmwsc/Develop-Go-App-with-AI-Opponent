// Preload: expose a minimal, safe API to the renderer.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("weiqi", {
  platform: process.platform,
  isElectron: true,
  versions: {
    electron: process.versions.electron,
    node: process.versions.node,
  },
});
