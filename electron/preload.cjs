const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopApi", {
  getAgentStatus: () => ipcRenderer.invoke("agents:status"),
  openAgentInstallGuide: (agentId) => ipcRenderer.invoke("agents:open-install-guide", agentId),
});
