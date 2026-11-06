import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The frontend fetches data branch JSON at RUNTIME, never at build time. A data
// refresh must not require a redeploy. See ARCHITECTURE.md section 1.
//
// There are no secrets here and there never will be. If the frontend ever needs
// a key, the design is wrong (ARCHITECTURE.md section 8). VITE_DATA_OWNER and
// VITE_DATA_REPO are public repository coordinates, not credentials.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
