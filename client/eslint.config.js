// @ts-check
const eslint = require("@eslint/js");
const { defineConfig } = require("eslint/config");
const tseslint = require("typescript-eslint");
const angular = require("angular-eslint");

module.exports = defineConfig([
  {
    // Generated from the FastAPI OpenAPI schema by scripts/gen-api-types.mjs.
    // openapi-typescript emits index signatures and mixes interface/type, which
    // the stylistic rules reject; the file is never hand-edited.
    ignores: ["src/app/core/api/schema.d.ts"],
  },
  {
    files: ["**/*.ts"],
    extends: [
      eslint.configs.recommended,
      tseslint.configs.recommended,
      tseslint.configs.stylistic,
      angular.configs.tsRecommended,
    ],
    processor: angular.processInlineTemplates,
    rules: {
      "@angular-eslint/directive-selector": [
        "error",
        {
          type: "attribute",
          prefix: "app",
          style: "camelCase",
        },
      ],
      "@angular-eslint/component-selector": [
        "error",
        {
          type: "element",
          prefix: "app",
          style: "kebab-case",
        },
      ],
      // Angular 22 flips the default to OnPush; the framework migration stamps
      // `ChangeDetectionStrategy.Eager` on every component that had no explicit
      // strategy, to keep behaviour identical. The rule would reject all of them.
      "@angular-eslint/prefer-on-push-component-change-detection": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-empty-function": "off",
      "@typescript-eslint/no-inferrable-types": "off",
    },
  },
  {
    files: ["**/*.html"],
    extends: [
      angular.configs.templateRecommended,
      angular.configs.templateAccessibility,
    ],
    rules: {
      "@angular-eslint/template/click-events-have-key-events": "warn",
      // A <details> is focused through its own <summary>; its keydown handlers
      // (Escape to close) only catch what bubbles up from that control and the
      // panel inside, so the container needs no tab stop of its own.
      "@angular-eslint/template/interactive-supports-focus": ["warn", { allowList: ["form", "details"] }],
      "@angular-eslint/template/no-autofocus": "warn",
      "@angular-eslint/template/label-has-associated-control": "warn",
    },
  }
]);
