import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("desktop", {
  isElectron: true,
  getAppVersion: () => process.env.npm_package_version || process.versions.electron,
});
