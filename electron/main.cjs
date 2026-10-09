const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { execFile, execFileSync, spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;
let backendProcess = null;
let frontendProcess = null;
let frontendServer = null;
let mainWindow = null;
let logFilePath = null;

app.setName("AI Shift Scheduler");

function timestamp() {
  return new Date().toISOString();
}

function getLogFilePath() {
  if (logFilePath) return logFilePath;
  const baseDir = app.isReady() ? app.getPath("userData") : path.join(app.getPath("temp"), "AI Shift Scheduler");
  const logDir = path.join(baseDir, "logs");
  fs.mkdirSync(logDir, { recursive: true });
  logFilePath = path.join(logDir, "startup.log");
  return logFilePath;
}

function log(message, details) {
  const line = `[${timestamp()}] ${message}${details ? ` ${details}` : ""}\n`;
  try {
    fs.appendFileSync(getLogFilePath(), line, "utf-8");
  } catch {
    // Logging must never become the reason the app fails to start.
  }
}

function errorToString(error) {
  if (error instanceof Error) return `${error.message}\n${error.stack ?? ""}`;
  return String(error);
}

process.on("uncaughtException", (error) => {
  log("uncaughtException", errorToString(error));
  showStartupError("예기치 않은 Electron 오류가 발생했습니다.", error);
});

process.on("unhandledRejection", (reason) => {
  log("unhandledRejection", errorToString(reason));
  showStartupError("비동기 시작 작업 중 오류가 발생했습니다.", reason);
});

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function isPackaged() {
  return app.isPackaged;
}

function commandExists(command) {
  return new Promise((resolve) => {
    const check = execFile("where.exe", [command], { windowsHide: true });
    check.once("close", (code) => resolve(code === 0));
    check.once("error", () => resolve(false));
  });
}

function commandVersion(command) {
  return new Promise((resolve) => {
    const child = spawn(command, ["--version"], { windowsHide: true });
    let output = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ installed: true, authenticated: false, version: output.trim() || null });
    }, 3000);
    child.stdout?.on("data", (data) => { output += data.toString(); });
    child.stderr?.on("data", (data) => { output += data.toString(); });
    child.once("error", () => {
      clearTimeout(timer);
      resolve({ installed: false, authenticated: false, version: null });
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      resolve({ installed: code === 0, authenticated: code === 0, version: output.trim() || null });
    });
  });
}

async function getAgentStatus() {
  const agents = [];
  for (const [id, command, name] of [["codex", "codex", "Codex CLI"], ["claude", "claude", "Claude Code"]]) {
    const installed = await commandExists(command);
    const status = installed ? await commandVersion(command) : { installed: false, authenticated: false, version: null };
    agents.push({ id, name, command, ...status });
  }
  return agents;
}

function backendExecutable() {
  if (isPackaged()) return path.join(process.resourcesPath, "backend", "workscheduler-api.exe");
  return path.join(projectRoot(), "backend", ".venv", "Scripts", "python.exe");
}

function appendChildOutput(prefix, data) {
  String(data)
    .split(/\r?\n/)
    .filter(Boolean)
    .forEach((line) => log(prefix, line));
}

function startBackend() {
  const dataDir = path.join(app.getPath("userData"), "data");
  fs.mkdirSync(dataDir, { recursive: true });
  const databaseUrl = `sqlite:///${path.join(dataDir, "workscheduler.db").replaceAll("\\", "/")}`;
  const env = {
    ...process.env,
    DATABASE_URL: databaseUrl,
    BACKEND_CORS_ORIGINS: "http://localhost:3000,http://127.0.0.1:3000,null",
    PYTHONPATH: isPackaged() ? undefined : path.join(projectRoot(), "backend"),
  };
  if (isPackaged()) {
    const executable = backendExecutable();
    if (!fs.existsSync(executable)) throw new Error(`Bundled backend not found: ${executable}`);
    log("starting packaged backend", `executable="${executable}" cwd="${dataDir}" database="${databaseUrl}"`);
    backendProcess = spawn(executable, [], { cwd: dataDir, env: { ...env, WORKSCHEDULER_HOST: "127.0.0.1", WORKSCHEDULER_PORT: String(BACKEND_PORT) }, windowsHide: true });
  } else {
    log("starting development backend", `executable="${backendExecutable()}" cwd="${path.join(projectRoot(), "backend")}"`);
    backendProcess = spawn(backendExecutable(), ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)], { cwd: path.join(projectRoot(), "backend"), env, windowsHide: true });
  }
  backendProcess.stdout?.on("data", (data) => appendChildOutput("backend stdout", data));
  backendProcess.stderr?.on("data", (data) => appendChildOutput("backend stderr", data));
  backendProcess.once("spawn", () => log("backend process spawned", `pid=${backendProcess.pid}`));
  backendProcess.once("error", (error) => {
    log("backend process error", errorToString(error));
    dialog.showErrorBox("백엔드 시작 실패", error.message);
  });
  backendProcess.once("exit", (code, signal) => {
    log("backend process exit", `code=${code} signal=${signal}`);
  });
}

function startFrontend() {
  if (isPackaged()) {
    const frontendRoot = path.join(process.resourcesPath, "frontend", "out");
    if (!fs.existsSync(path.join(frontendRoot, "index.html"))) throw new Error(`Bundled frontend not found: ${frontendRoot}`);
    frontendServer = http.createServer((request, response) => {
      const url = new URL(request.url || "/", `http://127.0.0.1:${FRONTEND_PORT}`);
      const decodedPath = decodeURIComponent(url.pathname);
      const candidate = path.normalize(path.join(frontendRoot, decodedPath === "/" ? "index.html" : decodedPath));
      const safeRoot = path.resolve(frontendRoot);
      let filePath = candidate.startsWith(safeRoot) ? candidate : path.join(frontendRoot, "index.html");
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) filePath = path.join(frontendRoot, "index.html");
      const ext = path.extname(filePath).toLowerCase();
      const contentTypes = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
      };
      response.setHeader("Content-Type", contentTypes[ext] || "application/octet-stream");
      fs.createReadStream(filePath)
        .once("error", (error) => {
          log("frontend static read error", errorToString(error));
          response.statusCode = 500;
          response.end("frontend asset read failed");
        })
        .pipe(response);
    });
    frontendServer.listen(FRONTEND_PORT, "127.0.0.1", () => {
      log("packaged frontend server listening", `http://127.0.0.1:${FRONTEND_PORT}`);
    });
    frontendServer.once("error", (error) => {
      log("frontend server error", errorToString(error));
    });
    return;
  }
  log("starting development frontend", `cwd="${path.join(projectRoot(), "frontend")}"`);
  frontendProcess = spawn(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", String(FRONTEND_PORT)], {
    cwd: path.join(projectRoot(), "frontend"),
    env: { ...process.env, NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}` },
    windowsHide: true,
  });
  frontendProcess.stdout?.on("data", (data) => appendChildOutput("frontend stdout", data));
  frontendProcess.stderr?.on("data", (data) => appendChildOutput("frontend stderr", data));
  frontendProcess.once("spawn", () => log("frontend process spawned", `pid=${frontendProcess.pid}`));
  frontendProcess.once("error", (error) => {
    log("frontend process error", errorToString(error));
    dialog.showErrorBox("프런트엔드 시작 실패", error.message);
  });
  frontendProcess.once("exit", (code, signal) => {
    log("frontend process exit", `code=${code} signal=${signal}`);
  });
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const ready = await new Promise((resolve) => {
      const request = http.get(`http://127.0.0.1:${BACKEND_PORT}/api/health`, (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      });
      request.on("error", () => resolve(false));
      request.setTimeout(500, () => {
        request.destroy();
        resolve(false);
      });
    });
    log("backend health check", `attempt=${attempt + 1} ready=${ready}`);
    if (ready) {
      log("backend ready");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Local backend did not become ready");
}

async function waitForFrontend() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const ready = await new Promise((resolve) => {
      const request = http.get(`http://127.0.0.1:${FRONTEND_PORT}/`, (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      });
      request.on("error", () => resolve(false));
      request.setTimeout(500, () => {
        request.destroy();
        resolve(false);
      });
    });
    log("frontend health check", `attempt=${attempt + 1} ready=${ready}`);
    if (ready) {
      log("frontend ready");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Local frontend did not become ready");
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 960,
    minHeight: 720,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    log("browser load failed", `code=${errorCode} description="${errorDescription}" url="${validatedURL}"`);
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    log("renderer process gone", JSON.stringify(details));
  });
  mainWindow.once("closed", () => {
    log("main window closed");
    mainWindow = null;
  });
  await waitForBackend();
  await waitForFrontend();
  const targetUrl = `http://127.0.0.1:${FRONTEND_PORT}`;
  log("loading main window", targetUrl);
  await mainWindow.loadURL(targetUrl);
  log("main window loaded");
}

function showStartupError(title, error) {
  const message = errorToString(error);
  log("startup error", message);
  if (!app.isReady()) return;
  const logPath = getLogFilePath();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorHtml(title, message, logPath))}`).catch(() => {});
    return;
  }
  mainWindow = new BrowserWindow({
    width: 920,
    height: 620,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorHtml(title, message, logPath))}`).catch(() => {});
}

function errorHtml(title, message, logPath) {
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#0f172a;background:#f8fafc}main{max-width:860px}pre{white-space:pre-wrap;background:#fff;border:1px solid #cbd5e1;padding:16px;border-radius:8px}code{background:#e2e8f0;padding:2px 4px;border-radius:4px}</style></head>
<body><main><h1>${escapeHtml(title)}</h1><p>프로그램 시작 중 문제가 발생했습니다. 아래 로그 파일을 확인해 주세요.</p><p><code>${escapeHtml(logPath)}</code></p><pre>${escapeHtml(message)}</pre></main></body></html>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stopProcessTree(child, label) {
  if (!child || child.killed || !child.pid) return;
  log(`stopping ${label} process tree`, `pid=${child.pid}`);
  if (process.platform === "win32") {
    try {
      const output = execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, encoding: "utf-8" });
      if (output) appendChildOutput(`${label} taskkill stdout`, output);
      log(`${label} process tree stopped`);
    } catch (error) {
      log(`${label} taskkill error`, errorToString(error));
    }
  } else {
    child.kill();
  }
}

ipcMain.handle("agents:status", () => getAgentStatus());
ipcMain.handle("agents:open-install-guide", async (_event, agentId) => {
  const urls = { codex: "https://github.com/openai/codex", claude: "https://docs.anthropic.com/en/docs/claude-code/overview" };
  if (!Object.hasOwn(urls, agentId)) throw new Error("Unknown agent");
  await shell.openExternal(urls[agentId]);
  return { opened: true };
});

app.whenReady().then(async () => {
  log("app ready", `packaged=${isPackaged()} appPath="${app.getAppPath()}" resourcesPath="${process.resourcesPath}" userData="${app.getPath("userData")}" execPath="${process.execPath}"`);
  try {
    startBackend();
    startFrontend();
    await createWindow();
  } catch (error) {
    showStartupError("AI Shift Scheduler 시작 실패", error);
  }
});

app.on("before-quit", () => {
  log("app before-quit");
  if (frontendServer) frontendServer.close(() => log("frontend server closed"));
  stopProcessTree(frontendProcess, "frontend");
  stopProcessTree(backendProcess, "backend");
});

app.on("window-all-closed", () => {
  log("window-all-closed");
  if (process.platform !== "darwin") app.quit();
});
