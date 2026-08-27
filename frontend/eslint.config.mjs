import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const nextConfigDirectory = dirname(
  fileURLToPath(import.meta.resolve('eslint-config-next/package.json')),
);

// FlatCompat otherwise resolves legacy plugins from the project root. pnpm
// correctly keeps eslint-config-next's plugins beside that package, so point
// the resolver at the dependency that declares them instead of relying on a
// hoisted node_modules layout that pnpm does not promise.
const compat = new FlatCompat({
  baseDirectory: __dirname,
  resolvePluginsRelativeTo: nextConfigDirectory,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // `.next-e2e/**` is the Playwright runner's build output, which is a
    // separate directory precisely so it is never mistaken for the shipped
    // one — including by tools that were told about `.next` alone.
    ignores: [".next/**", ".next-e2e/**", "out/**", "build/**", "next-env.d.ts", "src/lib/generated/**"],
  },
];

export default eslintConfig;
