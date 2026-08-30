import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypeScript,
  {
    // This application targets React 18. Several forms intentionally hydrate
    // API-backed defaults in effects; React 19's advisory rule is not yet
    // applicable to this runtime.
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
  globalIgnores([".next/**", "node_modules/**", "playwright-report/**", "playwright-report-real/**", "test-results/**", "test-results-real/**", "coverage/**", "next-env.d.ts"]),
]);
