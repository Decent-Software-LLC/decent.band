import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  publicDir: "site-public",
  build: {
    rollupOptions: {
      input: resolve(import.meta.dirname, "index.html"),
    },
  },
});
