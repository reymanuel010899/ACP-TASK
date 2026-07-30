import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    // Mirrors tsconfig.json's "@/*" -> "./src/*" path mapping, which
    // Next.js resolves natively but Vitest does not pick up on its own.
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // Component tests (U4) opt into jsdom per-file via a leading
    // `// @vitest-environment jsdom` comment; the rest of the suite stays on
    // the faster/simpler `node` environment above. jsdom defaults to an
    // opaque `about:blank` origin, which makes `localStorage`/
    // `sessionStorage` throw `SecurityError: ... opaque origins` -- giving it
    // a real http(s) URL here fixes that for every jsdom-environment test
    // file without each one repeating the option.
    //
    // Separately, modern Node ships its OWN global `localStorage`/
    // `sessionStorage` (gated behind `--localstorage-file`, unusable without
    // it). Vitest's jsdom environment setup only overrides a global that
    // Node hasn't already claimed, so with Node's stub present,
    // `window.localStorage` silently resolves to Node's non-functional
    // version instead of jsdom's real one. `package.json`'s `test` script
    // runs with `NODE_OPTIONS=--no-experimental-webstorage` to keep Node
    // from claiming those globals in the first place, letting jsdom's own
    // (working) implementation through -- see `SessionProvider.tsx` and
    // `usernameMap.ts`, both of which rely on real `localStorage`/
    // `sessionStorage` behavior in their tests.
    environmentOptions: {
      jsdom: {
        url: "http://localhost:3000",
      },
    },
  },
});
