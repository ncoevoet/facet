#!/usr/bin/env node
// Fails when a Material Symbols/Icons ligature name written as a literal in
// `src/app/**/*.ts` is not a ligature of the font the app ships. An unknown name
// does not error: the glyph silently renders as the raw word (`view_column_2`),
// which is how three icons shipped broken.
//
// Scanned (non-spec `.ts` files only):
//   - `<mat-icon ...>name</mat-icon>` with a literal body
//   - `icon="name"` and `icon: 'name'`
//   - every string value of a `const *_ICONS` record, and of any const whose
//     name contains "icon" in a `*.pipe.ts` / `*.pipes.ts` file
// Bindings and interpolations (`[icon]="x"`, `{{ x }}`, `'' | pipe`) are ignored,
// and so is any value that is not a bare lowercase word (the `✦` mark, CSS classes).
//
// Usage: node check-icon-ligatures.mjs [srcRoot]   (default: ../src/app)
//
// The ligature list `material-icons-ligatures.json` is generated from the shipped
// font `client/public/fonts/flUhRq6tzZclQEJ-Vdg-IuiaDsNc.woff2`. Regenerate it when the
// font changes: read the GSUB lookup type 4 (ligature) substitutions with fontTools
// (`python -I`), join the cmap characters of `[first] + Component` of each ligature
// into a name, and write the sorted unique names as a JSON array.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SRC_ROOT = resolve(process.argv[2] ?? join(HERE, '..', 'src', 'app'));
const LIGATURES = new Set(JSON.parse(readFileSync(join(HERE, 'material-icons-ligatures.json'), 'utf8')));
const BARE_WORD = /^[a-z][a-z0-9_]*$/;

function collectFiles(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      files.push(...collectFiles(fullPath));
    } else if (extname(entry) === '.ts' && !entry.endsWith('.spec.ts')) {
      files.push(fullPath);
    }
  }
  return files;
}

function lineAt(content, index) {
  let line = 1;
  for (let k = 0; k < index; k++) {
    if (content[k] === '\n') line++;
  }
  return line;
}

// Returns the index just past the `}` matching the `{` at `open`, skipping strings.
function matchingBrace(content, open) {
  let depth = 0;
  for (let i = open; i < content.length; i++) {
    const ch = content[i];
    if (ch === "'" || ch === '"' || ch === '`') {
      i++;
      while (i < content.length && content[i] !== ch) {
        if (content[i] === '\\') i++;
        i++;
      }
    } else if (ch === '{') {
      depth++;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) return i + 1;
    }
  }
  return content.length;
}

function scanFile(path, content) {
  const found = [];
  const add = (index, name) => found.push({ line: lineAt(content, index), name });
  for (const m of content.matchAll(/<mat-icon\b[^>]*>\s*([a-z0-9_]+)\s*<\/mat-icon>/g)) {
    add(m.index, m[1]);
  }
  for (const m of content.matchAll(/(?<![\w[\].-])icon="([^"]*)"/g)) {
    if (BARE_WORD.test(m[1])) add(m.index, m[1]);
  }
  for (const m of content.matchAll(/\bicon\s*:\s*(['"])([^'"]*)\1/g)) {
    if (BARE_WORD.test(m[2])) add(m.index, m[2]);
  }
  const iconNamePattern = /\.pipes?\.ts$/.test(path) ? /_ICONS$|icon/i : /_ICONS$/;
  for (const m of content.matchAll(/\bconst\s+(\w+)\b[^=;]*=\s*\{/g)) {
    if (!iconNamePattern.test(m[1])) continue;
    const open = m.index + m[0].length - 1;
    const body = content.slice(open, matchingBrace(content, open));
    for (const v of body.matchAll(/:\s*(['"])([^'"]*)\1/g)) {
      if (BARE_WORD.test(v[2])) add(open + v.index, v[2]);
    }
  }
  return found;
}

const unknown = new Map();
const checked = new Set();
let fileCount = 0;
for (const file of collectFiles(SRC_ROOT)) {
  fileCount++;
  for (const { line, name } of scanFile(file, readFileSync(file, 'utf8'))) {
    checked.add(name);
    if (LIGATURES.has(name)) continue;
    const where = `${relative(SRC_ROOT, file)}:${line}`;
    unknown.set(name, [...(unknown.get(name) ?? []), where]);
  }
}

if (unknown.size > 0) {
  console.error('Icon names missing from the shipped Material Icons font (they render as raw text):');
  for (const [name, wheres] of [...unknown].sort()) {
    console.error(`  ${name}  (${[...new Set(wheres)].join(', ')})`);
  }
  process.exit(1);
}
// A clean pass over nothing would read the same as a real one, so say how much was checked.
console.log(`check-icon-ligatures: all ${checked.size} literal icon names in ${fileCount} files are in the shipped font.`);
