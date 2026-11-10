import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const SCRIPT_PATH = join(dirname(fileURLToPath(import.meta.url)), 'check-icon-ligatures.mjs');

function run(files) {
  const root = mkdtempSync(join(tmpdir(), 'icon-ligatures-test-'));
  try {
    for (const [path, content] of Object.entries(files)) {
      mkdirSync(dirname(join(root, path)), { recursive: true });
      writeFileSync(join(root, path), content);
    }
    const stdout = execFileSync('node', [SCRIPT_PATH, root], { encoding: 'utf8', stdio: 'pipe' });
    return { status: 0, stdout, stderr: '' };
  } catch (error) {
    return { status: error.status, stdout: error.stdout ?? '', stderr: error.stderr ?? '' };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('passes on known ligatures in every scanned shape', () => {
  const r = run({
    'a.ts': `const t = '<mat-icon>home</mat-icon> <app-x icon="hdr_strong"></app-x>'; const o = { icon: 'vertical_split' };`,
    'b.pipes.ts': `const KIND_ICONS: Record<string, string> = { a: 'screenshot' };\nconst WEIGHT_ICONS = { x: '✦', y: 'grain' };`,
  });
  assert.equal(r.status, 0);
});

test('flags an unknown literal in a mat-icon body', () => {
  const r = run({ 'a.ts': 'const t = `<mat-icon>view_column_2</mat-icon>`;' });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /view_column_2/);
});

test('flags icon="…" and icon: \'…\'', () => {
  const r = run({ 'a.ts': `const t = '<x icon="dynamic_range"></x>'; const o = { icon: 'folder_move' };` });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /dynamic_range/);
  assert.match(r.stderr, /folder_move/);
});

test('flags unknown values of a const *_ICONS record, including nested ones', () => {
  const r = run({ 'a.ts': `export const SORT_ICONS = { a: 'home', b: { text: 'nope_icon' } };` });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /nope_icon/);
});

test('flags unknown values in a *.pipes.ts icon map but not in other consts', () => {
  const pipe = run({ 'a.pipes.ts': `const kindIcons = { a: 'bogus_one' };` });
  assert.equal(pipe.status, 1);
  assert.match(pipe.stderr, /bogus_one/);
  const other = run({ 'a.ts': `const LABELS = { a: 'bogus_one' };` });
  assert.equal(other.status, 0);
});

test('ignores bindings, interpolations, spec files and non-word values', () => {
  const r = run({
    'a.ts': `const t = '<mat-icon>{{ x }}</mat-icon> <a [icon]="bogus" icon="a b"></a> <mat-icon>✦</mat-icon>';`,
    'a.spec.ts': `const t = '<mat-icon>bogus_name</mat-icon>';`,
  });
  assert.equal(r.status, 0);
});
