/// <reference types="vite/client" />

// Public repository coordinates, baked in at build time. Not credentials: they
// are the address of a public branch. If this interface ever needs a key, the
// design is wrong (ARCHITECTURE.md section 8).
interface ImportMetaEnv {
  readonly VITE_DATA_OWNER?: string;
  readonly VITE_DATA_REPO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
