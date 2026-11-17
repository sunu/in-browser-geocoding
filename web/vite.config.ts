import { defineConfig, type Plugin } from "vite";

// DuckDB-WASM reads the large Parquet files with HTTP range requests only if the server says it supports
// them (Accept-Ranges). The Vite dev server answers range requests but does not send the header.
const isData = (url?: string) => /^\/(data|countries|world)\//.test(url ?? "");
const acceptRanges: Plugin = {
  name: "accept-ranges",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (isData(req.url)) {
        res.setHeader("Accept-Ranges", "bytes");
        // DuckDB-WASM cannot handle 304 answers. Never answer a conditional request for data files.
        delete req.headers["if-none-match"];
        delete req.headers["if-modified-since"];
      }
      next();
    });
  },
  configurePreviewServer(server) {
    server.middlewares.use((req, res, next) => {
      if (isData(req.url)) res.setHeader("Accept-Ranges", "bytes");
      next();
    });
  },
};

export default defineConfig({
  plugins: [acceptRanges],
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm", "onnxruntime-web", "onnxruntime-node"], entries: ["index.html"] },
  server: { headers: { "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "credentialless" } },
  build: { target: "es2022" },
});
