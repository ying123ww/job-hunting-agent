/// <reference types="vite/client" />

declare global {
  interface Window {
    desktop?: {
      isElectron: boolean;
      getAppVersion: () => string;
    };
  }
}

export {};
