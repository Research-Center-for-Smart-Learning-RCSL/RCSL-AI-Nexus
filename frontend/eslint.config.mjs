import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ baseDirectory: __dirname });

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
