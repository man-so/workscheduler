const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { execFile, spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;
let backendProcess = null;
let frontendProcess = null;

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
    backendProcess = spawn(executable, [], { cwd: dataDir, env: { ...env, WORKSCHEDULER_HOST: "127.0.0.1", WORKSCHEDULER_PORT: String(BACKEND_PORT) }, windowsHide: true });
  } else {
    backendProcess = spawn(backendExecutable(), ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)], { cwd: path.join(projectRoot(), "backend"), env, windowsHide: true });
  }
  backendProcess.once("error", (error) => dialog.showErrorBox("백엔드 시작 실패", error.message));
}

function startFrontend() {
  if (isPackaged()) return;
  frontendProcess = spawn(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", String(FRONTEND_PORT)], {
    cwd: path.join(projectRoot(), "frontend"),
    env: { ...process.env, NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}` },
    windowsHide: true,
  });
  frontendProcess.once("error", (error) => dialog.showErrorBox("프런트엔드 시작 실패", error.message));
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
    if (ready) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Local backend did not become ready");
}

async function createWindow() {
  const window = new BrowserWindow({
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
  await waitForBackend();
  if (isPackaged()) await window.loadFile(path.join(process.resourcesPath, "frontend", "out", "index.html"));
  else await window.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`);
}

ipcMain.handle("agents:status", () => getAgentStatus());
ipcMain.handle("agents:open-install-guide", async (_event, agentId) => {
  const urls = { codex: "https://github.com/openai/codex", claude: "https://docs.anthropic.com/en/docs/claude-code/overview" };
  if (!Object.hasOwn(urls, agentId)) throw new Error("Unknown agent");
  await shell.openExternal(urls[agentId]);
  return { opened: true };
});

app.whenReady().then(async () => {
  try {
    startBackend();
    startFrontend();
    await createWindow();
  } catch (error) {
    dialog.showErrorBox("AI Shift Scheduler 시작 실패", error instanceof Error ? error.message : String(error));
    app.quit();
  }
});

app.on("before-quit", () => {
  if (frontendProcess && !frontendProcess.killed) frontendProcess.kill();
  if (backendProcess && !backendProcess.killed) backendProcess.kill();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
