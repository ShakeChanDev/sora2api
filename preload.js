const { ipcRenderer, contextBridge, shell } = require("electron");

window.elecAPI = {
  toInstall: () => ipcRenderer.invoke("install"),
  onUpdate: (callback) => ipcRenderer.on("update", callback),
  onDownloaded: (callback) => ipcRenderer.on("downloaded", callback),
};

const receiveChannels = [
  "folder-selected",
  "file-selected",
  "current-version",
  "checking-for-update",
  "update-available",
  "update-not-available",
  "download-progress",
  "update-downloaded",
  "update-error",
  "read-excel",
];

const rpaReceiveChannels = [
  "rpa-plan-start",
  "rpa-operating-log",
  "rpa-plan-end",
  "rpa-error",
  "rpa-profile-end",
  "rpa-log",
  "rpa-output",
  "rpa-running",
  "rpa-profile-start-http",
  "rpa-profile-end-http",
  "rpa-log-http",
  "rpa-output-http",
  "rpa-plan-end-http",
  "rpa-plan-end-update-end",
  "rpa-stop-queue-plan",
  "rpa-profile-launch",
  "rpa-schedule-execute",
  "rpa-schedule-execute-end",
  "schedule-rpa-end",
  "rpa-local-log-list",
  "rpa-local-log-detail",
  "rpa-local-log-delete-success"
];

// create context bridge
contextBridge.exposeInMainWorld("elecAPI", {
  openURL: (url, options = {}) => ipcRenderer.send('open-external-url', { url, options }),
  openFolder: (dir) => shell.openPath(dir),
  send: (channel, data) => {
    // whitelist channels
    let validChannels = ["toMain"];
    if (validChannels.includes(channel)) {
      ipcRenderer.send(channel, data);
    }
  },
  receive: (channel, func) => {
    if (receiveChannels.includes(channel)) {
      // Deliberately strip event as it includes `sender`
      ipcRenderer.on(channel, (event, ...args) => func(...args));
    }
  },
  unReceive: (channel) => {
    if (receiveChannels.includes(channel)) {
      ipcRenderer.removeAllListeners(channel);
    }
  },
  rpaReceive: (channel, func) => {
    if (rpaReceiveChannels.includes(channel)) {
      ipcRenderer.on(channel, (event, ...args) => func(...args));
    }
  },
  removeRpaListener: (channel) => {
    if (rpaReceiveChannels.includes(channel)) {
      ipcRenderer.removeAllListeners(channel);
    }
  },
  onScheduleRpaEnd: (callback) =>
    ipcRenderer.on("schedule-rpa-end", (_event, value) => callback(value)),
});
