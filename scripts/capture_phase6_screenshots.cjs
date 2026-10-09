const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const http = require("http");
const path = require("path");

const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "artifacts", "phase6", "screenshots");
const pagePath = path.join(root, "frontend", "out", "index.html");

const scenarios = [
  { prefix: "A.", name: "calendar_8_staff.png" },
  { prefix: "C.", name: "calendar_15_staff.png" },
  { prefix: "D.", name: "calendar_25_staff.png" },
];

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function startStaticServer() {
  const server = http.createServer((request, response) => {
    const requested = request.url === "/" ? "/index.html" : request.url;
    const filePath = path.resolve(path.join(root, "frontend", "out", requested.replace(/^\//, "")));
    if (!filePath.startsWith(path.resolve(path.join(root, "frontend", "out")))) {
      response.writeHead(403);
      response.end();
      return;
    }
    fs.readFile(filePath, (error, content) => {
      if (error) {
        response.writeHead(404);
        response.end();
        return;
      }
      const contentType = filePath.endsWith(".js") ? "text/javascript" : filePath.endsWith(".css") ? "text/css" : "text/html";
      response.writeHead(200, { "Content-Type": contentType });
      response.end(content);
    });
  });
  return new Promise((resolve) => server.listen(8013, "127.0.0.1", () => resolve(server)));
}

async function loadScenario(window, prefix) {
  await window.webContents.executeJavaScript(`
    (async () => {
      const teamSelect = [...document.querySelectorAll("select")].find((select) =>
        [...select.options].some((option) => option.textContent.includes(${JSON.stringify(prefix)}))
      );
      if (!teamSelect) throw new Error("team select not found for ${prefix}; selects=" + document.querySelectorAll("select").length);
      const option = [...teamSelect.options].find((item) => item.textContent.includes(${JSON.stringify(prefix)}));
      teamSelect.value = option.value;
      teamSelect.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 2200));
      const monthInputs = [...document.querySelectorAll('input[type="number"]')].slice(-2);
      const setInput = (input, value) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };
      if (monthInputs.length >= 2) {
        setInput(monthInputs[0], "2026");
        setInput(monthInputs[1], "11");
      }
      console.log("numeric inputs", JSON.stringify([...document.querySelectorAll('input[type=number]')].map((input) => input.value)));
      await new Promise((resolve) => setTimeout(resolve, 500));
      const loadButton = [...document.querySelectorAll("button")].find((button) => button.textContent.includes("불러오기"));
      if (!loadButton) throw new Error("load button not found");
      loadButton.click();
      await new Promise((resolve) => setTimeout(resolve, 2200));
      const calendarDay = [...document.querySelectorAll("button")].find((button) => /\d{1,2}일 · \d+명/.test(button.textContent));
      if (calendarDay) {
        window.scrollTo(0, calendarDay.getBoundingClientRect().top + window.scrollY - 80);
        console.log("calendar target", calendarDay.textContent.slice(0, 40), "scrollY", window.scrollY);
      } else {
        console.log("calendar target missing", JSON.stringify({versionHistory: document.body.innerText.includes("버전 이력"), currentVersion: document.body.innerText.includes("현재 버전"), bodyHeight: document.body.scrollHeight, scrollY: window.scrollY}));
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
      return document.body.innerText;
    })();
  `);
}

app.whenReady().then(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const staticServer = await startStaticServer();
  const window = new BrowserWindow({
    width: 1680,
    height: 1400,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.on("console-message", (_event, _level, message) => console.log("renderer:", message));
  await window.loadURL("http://127.0.0.1:8013/index.html");
  await wait(2500);
  console.log("loaded", pagePath, await window.webContents.executeJavaScript("JSON.stringify({text: document.body.innerText, selects: [...document.querySelectorAll('select')].map((select) => [...select.options].map((option) => option.textContent))})"));
  for (const scenario of scenarios) {
    console.log("capturing", scenario.prefix);
    await loadScenario(window, scenario.prefix);
    const image = await window.webContents.capturePage();
    const outputPath = path.join(outDir, scenario.name);
    fs.writeFileSync(outputPath, image.toPNG());
    console.log("wrote", outputPath, fs.statSync(outputPath).size);
  }
  await window.close();
  staticServer.close();
  app.quit();
}).catch((error) => {
  console.error(error);
  app.exit(1);
});
