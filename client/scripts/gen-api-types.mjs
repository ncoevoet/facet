// Generates client/src/app/core/api/schema.d.ts from the FastAPI application's
// OpenAPI schema, so the client's request and response types cannot drift from
// what the server actually declares.
//
// The intermediate openapi.json is NOT committed: it is written to a temp path
// and deleted. Two committed artifacts could disagree with each other, and then
// there would be two gates to keep honest instead of one.
//
// Run from the client/ directory:  npm run gen:api
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const clientDir = path.resolve(import.meta.dirname, '..');
const repoRoot = path.resolve(clientDir, '..');
const outPath = path.join(clientDir, 'src/app/core/api/schema.d.ts');

function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venv = path.join(repoRoot, 'venv/bin/python');
  if (fs.existsSync(venv)) return venv;
  return 'python';
}

// The pinned version is read from package.json rather than repeated here, so a
// Dependabot bump cannot leave the CI fallback generating with a different
// version than local development uses.
function pinnedGeneratorSpec() {
  const pkg = JSON.parse(fs.readFileSync(path.join(clientDir, 'package.json'), 'utf8'));
  const version = pkg.devDependencies?.['openapi-typescript'];
  if (!version) throw new Error('openapi-typescript is not a devDependency of client/package.json');
  return `openapi-typescript@${version}`;
}

// --default-non-nullable=false: a Pydantic field with a default is NOT in OpenAPI's
// `required` list, and every route here uses response_model_exclude_unset=True, so a
// defaulted field the handler never set is genuinely ABSENT from the wire. Without this
// the generator would promote those fields to required and the type would lie.
const GENERATOR_ARGS = ['--default-non-nullable=false'];

function runGenerator(schemaPath) {
  const local = path.join(clientDir, 'node_modules/.bin/openapi-typescript');
  const args = [schemaPath, ...GENERATOR_ARGS, '--output', outPath];
  if (fs.existsSync(local)) {
    execFileSync(local, args, { stdio: 'inherit', cwd: clientDir });
  } else {
    // --ignore-scripts: this branch downloads and installs openapi-typescript
    // (and its transitive tree) on demand, with no local lockfile to check
    // integrity hashes against, so nothing should be allowed to run an
    // install/postinstall lifecycle script.
    execFileSync(
      'npx',
      ['--yes', '--ignore-scripts', pinnedGeneratorSpec(), ...args],
      { stdio: 'inherit', cwd: clientDir },
    );
  }
}

const schemaPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'facet-openapi-')), 'openapi.json');
try {
  execFileSync(resolvePython(), [path.join(repoRoot, 'scripts/dump_openapi.py'), schemaPath], {
    stdio: 'inherit',
    cwd: repoRoot,
  });
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  runGenerator(schemaPath);
  console.log(`wrote ${path.relative(repoRoot, outPath)}`);
} finally {
  fs.rmSync(path.dirname(schemaPath), { recursive: true, force: true });
}
