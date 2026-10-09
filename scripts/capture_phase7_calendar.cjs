const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "artifacts", "phase7");
const outPath = path.join(outDir, "phase7_calendar_electron.png");

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function preparePilotCalendar(window) {
  return window.webContents.executeJavaScript(`
    (async () => {
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      await wait(2500);
      const selects = [...document.querySelectorAll("select")];
      const teamSelect = selects.find((select) => [...select.options].some((option) => option.textContent.includes("Phase 7 Pilot")));
      if (!teamSelect) throw new Error("Phase 7 Pilot team option not found");
      const options = [...teamSelect.options].filter((option) => option.textContent.includes("Phase 7 Pilot"));
      const option = options[options.length - 1];
      teamSelect.value = option.value;
      teamSelect.dispatchEvent(new Event("change", { bubbles: true }));
      await wait(2200);
      const numberInputs = [...document.querySelectorAll('input[type="number"]')].slice(-2);
      const setInput = (input, value) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };
      setInput(numberInputs[0], "2026");
      setInput(numberInputs[1], "11");
      await wait(500);
      const loadButton = [...document.querySelectorAll("button")].find((button) => button.textContent.includes("불러오기"));
      loadButton.click();
      await wait(3500);
      console.log("after load", JSON.stringify({
        hasCurrentVersion: document.body.innerText.includes("현재 버전"),
        hasCalendarCount: /\\d{1,2}일 · 16명/.test(document.body.innerText),
        bodyHeight: document.body.scrollHeight,
        scrollY: window.scrollY
      }));
      const calendarDay = [...document.querySelectorAll("button")].find((button) => /\\d{1,2}일 · 16명/.test(button.textContent));
      if (!calendarDay) throw new Error("Phase 7 calendar day not found");
      window.scrollTo(0, calendarDay.getBoundingClientRect().top + window.scrollY - 90);
      await wait(500);
      console.log("after scroll", JSON.stringify({ scrollY: window.scrollY, targetTop: calendarDay.getBoundingClientRect().top }));
      return document.body.innerText;
    })();
  `);
}

app.whenReady().then(async () => {
  fs.mkdirSync(outDir, { recursive: true });
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
  await window.loadURL("http://127.0.0.1:3000");
  await preparePilotCalendar(window);
  const image = await window.webContents.capturePage();
  fs.writeFileSync(outPath, image.toPNG());
  console.log(outPath);
  await window.close();
  app.quit();
}).catch((error) => {
  console.error(error);
  app.exit(1);
});
