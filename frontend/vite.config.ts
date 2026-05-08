import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import electron from "vite-plugin-electron/simple";

export default defineConfig(() => {
  const enableElectron = process.env.VITE_ENABLE_ELECTRON === "1";

  return {
    plugins: [
      vue(),
      ...(enableElectron
        ? [
            electron({
              main: {
                entry: "electron/main.ts",
              },
              preload: {
                input: "electron/preload.ts",
              },
              renderer: {},
            }),
          ]
        : []),
    ],
    server: {
      host: "127.0.0.1",
      port: 5173,
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: [],
      include: ["tests/unit/**/*.spec.ts"],
    },
  };
});
