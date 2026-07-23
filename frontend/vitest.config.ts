import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Default env stays "node" for plain unit tests (e.g. lib/*.test.ts);
    // .tsx component tests opt into jsdom via a `// @vitest-environment jsdom`
    // docblock at the top of the file instead of paying the jsdom cost globally.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
