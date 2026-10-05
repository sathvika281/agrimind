import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          // Dev only. Set VITE_PROXY_TARGET to point the proxy at another local backend.
          target: env.VITE_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
