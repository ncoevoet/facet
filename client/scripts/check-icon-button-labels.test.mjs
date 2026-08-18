import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const SCRIPT_PATH = join(dirname(fileURLToPath(import.meta.url)), 'check-icon-button-labels.mjs');

function writeFixture(root, relativePath, content) {
  const fullPath = join(root, relativePath);
  mkdirSync(dirname(fullPath), { recursive: true });
  writeFileSync(fullPath, content);
}

function runScanner(root) {
  try {
    const stdout = execFileSync('node', [SCRIPT_PATH], {
      encoding: 'utf8',
      env: { ...process.env, ICON_BUTTON_LABELS_SRC_ROOT: root },
    });
    return { status: 0, stdout, stderr: '' };
  } catch (error) {
    return { status: error.status, stdout: error.stdout ?? '', stderr: error.stderr ?? '' };
  }
}

function withFixtureRoot(callback) {
  const root = mkdtempSync(join(tmpdir(), 'icon-button-labels-test-'));
  try {
    callback(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('flags an icon-only button with no aria-label at all', () => {
  withFixtureRoot((root) => {
    writeFixture(
      root,
      'a/unlabelled.component.html',
      '<button mat-icon-button (click)="x()"><mat-icon>close</mat-icon></button>',
    );
    const result = runScanner(root);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /unlabelled\.component\.html:1 — no aria-label/);
  });
});

test('does not flag an icon-only button with a real static aria-label', () => {
  withFixtureRoot((root) => {
    writeFixture(
      root,
      'a/labelled.component.html',
      '<button mat-icon-button aria-label="Close"><mat-icon>close</mat-icon></button>',
    );
    const result = runScanner(root);
    assert.equal(result.status, 0);
    assert.match(result.stdout, /All icon-only buttons have a reliable accessible name\./);
  });
});

test('flags [attr.aria-label] ternary/||/?? bindings that can reach an empty string', () => {
  withFixtureRoot((root) => {
    writeFixture(
      root,
      'b/ternary-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="isActive ? \'\' : \'Close\'"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'b/or-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="label || \'\'"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'b/nullish-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="label ?? \'\'"><mat-icon>close</mat-icon></button>',
    );
    const result = runScanner(root);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /ternary-empty\.component\.html:1 — \[attr\.aria-label\] can evaluate to an empty/);
    assert.match(result.stderr, /or-empty\.component\.html:1 — \[attr\.aria-label\] can evaluate to an empty/);
    assert.match(result.stderr, /nullish-empty\.component\.html:1 — \[attr\.aria-label\] can evaluate to an empty/);
  });
});

test('does not flag an icon-only button commented out in the template (Finding 7 regression)', () => {
  withFixtureRoot((root) => {
    writeFixture(
      root,
      'c/commented-out.component.html',
      '<!-- <button mat-icon-button (click)="doThing()"><mat-icon>close</mat-icon></button> -->',
    );
    const result = runScanner(root);
    assert.equal(result.status, 0, `expected commented-out markup to be ignored, got:\n${result.stderr}`);
    assert.match(result.stdout, /All icon-only buttons have a reliable accessible name\./);
  });
});

test('self-guard: scans every fixture file and cannot silently match nothing', () => {
  withFixtureRoot((root) => {
    writeFixture(
      root,
      'a/unlabelled.component.html',
      '<button mat-icon-button (click)="x()"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'a/labelled.component.html',
      '<button mat-icon-button aria-label="Close"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'b/ternary-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="isActive ? \'\' : \'Close\'"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'b/or-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="label || \'\'"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'b/nullish-empty.component.html',
      '<button mat-icon-button [attr.aria-label]="label ?? \'\'"><mat-icon>close</mat-icon></button>',
    );
    writeFixture(
      root,
      'c/commented-out.component.html',
      '<!-- <button mat-icon-button (click)="doThing()"><mat-icon>close</mat-icon></button> -->',
    );
    writeFixture(
      root,
      'c/nested/deep-unlabelled.component.ts',
      "const template = `<button mat-icon-button><mat-icon>close</mat-icon></button>`;",
    );

    const result = runScanner(root);
    assert.equal(result.status, 1);

    const violationLines = result.stderr
      .split('\n')
      .filter((line) => / — /.test(line));
    assert.equal(
      violationLines.length,
      5,
      `expected exactly 5 violations across the 7 scanned fixtures (2 clean), got ${violationLines.length}:\n${result.stderr}`,
    );

    const flaggedBasenames = violationLines.map((line) => line.trim().split(':')[0].split('/').pop()).sort();
    assert.deepEqual(flaggedBasenames, [
      'deep-unlabelled.component.ts',
      'nullish-empty.component.html',
      'or-empty.component.html',
      'ternary-empty.component.html',
      'unlabelled.component.html',
    ]);
  });
});
