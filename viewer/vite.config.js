import { resolve } from "node:path";
import { defineConfig } from "vite";


const dependencyRoot = process.env.BIM_VIEWER_NODE_MODULES;
const aliases = dependencyRoot
  ? {
      "@thatopen/components": resolve(dependencyRoot, "@thatopen/components"),
      "@thatopen/components-front": resolve(dependencyRoot, "@thatopen/components-front"),
      "@thatopen/fragments": resolve(dependencyRoot, "@thatopen/fragments"),
      "camera-controls": resolve(dependencyRoot, "camera-controls"),
      "three": resolve(dependencyRoot, "three"),
      "web-ifc": resolve(dependencyRoot, "web-ifc"),
    }
  : {};

export default defineConfig({
  resolve: { alias: aliases },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 8000,
  },
});
