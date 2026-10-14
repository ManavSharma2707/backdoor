import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

// The long dashes (U+2014 and U+2013) are banned in everything a person reads (D-020).
const DASHES = new RegExp(`[${String.fromCharCode(0x2014)}${String.fromCharCode(0x2013)}]`);
const HEX_COLOUR = /#[0-9a-fA-F]{3,8}\b/;

const backroom = {
  rules: {
    "no-dash-characters": {
      meta: {
        type: "problem",
        messages: {
          dash: "Use a comma, colon, full stop or the word 'to' instead of a long dash.",
        },
        schema: [],
      },
      create(context) {
        const check = (node, text) => {
          if (DASHES.test(text)) context.report({ node, messageId: "dash" });
        };
        return {
          Literal(node) {
            if (typeof node.value === "string") check(node, node.value);
          },
          TemplateElement(node) {
            check(node, node.value.cooked ?? node.value.raw);
          },
          JSXText(node) {
            check(node, node.value);
          },
        };
      },
    },
    "no-hex-colours": {
      meta: {
        type: "problem",
        messages: { hex: "Use a colour token from styles/index.css, not a hex value." },
        schema: [],
      },
      create(context) {
        return {
          Literal(node) {
            if (typeof node.value === "string" && HEX_COLOUR.test(node.value)) {
              context.report({ node, messageId: "hex" });
            }
          },
        };
      },
    },
  },
};

export default tseslint.config(
  { ignores: ["dist", "coverage", "screenshots", "node_modules", "src/types/api.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks, "jsx-a11y": jsxA11y, backroom },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      "backroom/no-dash-characters": "error",
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-console": "error",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["src/components/**/*.{ts,tsx}", "src/features/**/*.{ts,tsx}"],
    ignores: ["src/features/**/charts.tsx", "src/components/charts/**"],
    rules: { "backroom/no-hex-colours": "error" },
  },
  {
    files: ["**/*.mjs"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
);
