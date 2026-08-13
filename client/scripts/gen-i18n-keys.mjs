// Generates client/src/app/core/i18n/keys.ts from i18n/translations/en.json.
// Leaf values are the dot-path translation keys consumed by the `translate` pipe
// and I18nService.t(). The object mirrors the bundle structure verbatim (keys are
// kept as-is; non-identifier keys are quoted and accessed via bracket notation).
//
// Run from the client/ directory:  node scripts/gen-i18n-keys.mjs
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '..', '..');
const enPath = path.join(repoRoot, 'i18n/translations/en.json');
const outPath = path.join(repoRoot, 'client/src/app/core/i18n/keys.ts');

const en = JSON.parse(fs.readFileSync(enPath, 'utf8'));
const isIdent = (k) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k);

function emit(obj, prefix, indent) {
  const pad = '  '.repeat(indent);
  const lines = [];
  for (const [k, v] of Object.entries(obj)) {
    const dot = prefix ? `${prefix}.${k}` : k;
    const key = isIdent(k) ? k : JSON.stringify(k);
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      lines.push(`${pad}${key}: {`);
      lines.push(emit(v, dot, indent + 1));
      lines.push(`${pad}},`);
    } else {
      lines.push(`${pad}${key}: ${JSON.stringify(dot)},`);
    }
  }
  return lines.join('\n');
}

const header =
  '// AUTO-GENERATED from i18n/translations/en.json by scripts/gen-i18n-keys.mjs.\n' +
  '// Do not edit by hand -- run `node scripts/gen-i18n-keys.mjs` to regenerate.\n' +
  '// Leaf values are the dot-path translation keys used by the `translate` pipe and I18nService.t().\n' +
  '//\n' +
  '// I18N_KEYS re-exports the same table under a second name, for class-field initializers\n' +
  "// only: `protected readonly I18N = I18N;` looks harmless, but Vitest's unit-test builder\n" +
  '// runs specs through Vite\'s SSR transform, which rewrites references to imported bindings\n' +
  "// into namespace-property accesses. That transform's scope walker registers a class field's\n" +
  "// own *name* as a local binding, so in `protected readonly I18N = I18N` the initializer's\n" +
  '// right-hand `I18N` looks locally shadowed and the rewrite is skipped -- it then resolves to\n' +
  "// whatever raw `I18N` is in scope, which under an unlucky chunk layout is a *different* chunk's\n" +
  '// own uninitialised copy of this module (`undefined`), not the real table. Every template\n' +
  '// binding then dereferences `undefined` on first change detection. Initializing the field from\n' +
  '// `I18N_KEYS` instead uses a name the field does not shadow, so the rewrite fires correctly.\n' +
  '// Always initialize the `I18N` field from `I18N_KEYS`, never from `I18N` itself.\n\n';
const body =
  `export const I18N = {\n${emit(en, '', 1)}\n} as const;\n\n` +
  '/** Same table as {@link I18N}, exported under a distinct name for class-field initializers -- see header comment above. */\n' +
  'export const I18N_KEYS = I18N;\n';

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, header + body);

let leaves = 0;
(function count(o) {
  for (const v of Object.values(o)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) count(v);
    else leaves += 1;
  }
})(en);
console.log(`wrote ${path.relative(repoRoot, outPath)} (${leaves} keys)`);
