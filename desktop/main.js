// Electron main process.
//
// Responsibilities:
//   1. Spawn the Python FastAPI backend as a child process (packaged mode) or
//      assume it's already running (dev mode with --dev flag).
//   2. Create the BrowserWindow and load the built frontend (release) or
//      the Vite dev server (dev).
//   3. Clean up the Python process on app quit.
const { app, BrowserWindow, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

const isDev = process.argv.includes("--dev");
const BACKEND_PORT = 8000;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

let pyProc = null;
let mainWindow = null;

function waitForBackend(url, timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Backend startup timeout"));
        return;
      }
      const req = http.get(`${url}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          setTimeout(check, 500);
        }
        res.destroy();
      });
      req.on("error", () => setTimeout(check, 500));
      req.setTimeout(2000, () => {
        req.destroy();
        setTimeout(check, 500);
      });
    };
    check();
  });
}

function startBackend() {
  if (isDev) {
    // In dev, the backend is started separately via `uvicorn app.main:app`.
    return Promise.resolve();
  }
  const backendDir = path.join(process.resourcesPath, "backend");
  // Try python3 then python
  const py = process.env.WEIQI_PYTHON || "python3";
  pyProc = spawn(
    py,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
    { cwd: backendDir, stdio: ["ignore", "pipe", "pipe"] }
  );
  pyProc.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  pyProc.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  pyProc.on("exit", (code) => console.log(`Backend exited with ${code}`));
  return waitForBackend(BACKEND_URL);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#1a1a1a",
    title: "围棋 AI",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Open external links in browser, not in app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
  }
}

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (e) {
    console.error("Failed to start backend:", e.message);
  }
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (pyProc) {
    try {
      pyProc.kill();
    } catch {
      /* ignore */
    }
  }
});
