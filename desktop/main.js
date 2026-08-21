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
  // 生产模式优先使用 PyInstaller 打包的后端可执行文件，
  // 兼容回退到 python3 -m uvicorn（需要目标机器有 Python 环境）
  const backendDir = path.join(process.resourcesPath, "backend");
  const exeName = process.platform === "win32" ? "WeiqiAI.exe" : "WeiqiAI";
  const pyinstallerExe = path.join(backendDir, "WeiqiAI", exeName);
  const pyinstallerAlt = path.join(backendDir, exeName);

  let cmd, args;
  if (require("fs").existsSync(pyinstallerExe)) {
    cmd = pyinstallerExe;
    args = [];
  } else if (require("fs").existsSync(pyinstallerAlt)) {
    cmd = pyinstallerAlt;
    args = [];
  } else {
    // Fallback: 原始 Python 方式
    cmd = process.env.WEIQI_PYTHON || "python3";
    args = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)];
  }

  pyProc = spawn(cmd, args, {
    cwd: backendDir,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, WEIQI_PORT: String(BACKEND_PORT) },
  });
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
    // 生产模式：FastAPI 自身已 mount 前端静态文件，直接加载后端 URL
    // 这样所有 /api 请求同源，无需 CORS 或代理
    mainWindow.loadURL(`${BACKEND_URL}/`);
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
