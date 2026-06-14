import path from "node:path";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
    alias: {
      react: path.resolve(__dirname, "node_modules/react"),
      "react-dom": path.resolve(__dirname, "node_modules/react-dom"),
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom"],
  },
  server: {
    host: "0.0.0.0", // reachable from the host when running in a container
    port: 5173,
    // Windows + Docker bind mounts: native FS events don't propagate, so poll.
    watch: { usePolling: true },
    // Ensure the browser's HMR websocket targets the published host port.
    hmr: { clientPort: 5173 },
  },
});
