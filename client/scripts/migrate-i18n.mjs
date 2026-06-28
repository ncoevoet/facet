// One-shot codemod: replace magic i18n key strings with references to the
// generated I18N constants (src/app/core/i18n/keys.ts).
//   - templates:  '<key>' | translate     ->  I18N.<key> | translate
//   - TS calls:   .t('<key>')             ->  .t(I18N.<key>)
// Adds the I18N import to changed .ts files, and exposes `readonly I18N = I18N`
// on component classes whose template references the keys. Spec files are left
// untouched. Idempotent. Run from client/:  node scripts/migrate-i18n.mjs
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '..', '..');
const srcRoot = path.join(repoRoot, 'client/src');
const keysFile = path.join(repoRoot, 'client/src/app/core/i18n/keys.ts');
const en = JSON.parse(fs.readFileSync(path.join(repoRoot, 'i18n/translations/en.json'), 'utf8'));

const keys = new Set();
(function walk(o, p) {
  for (const [k, v] of Object.entries(o)) {
    const d = p ? `${p}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) walk(v, d);
    else keys.add(d);
  }
})(en, '');

const isIdent = (s) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(s);
const accessor = (dot) =>
  'I18N' + dot.split('.').map((s) => (isIdent(s) ? `.${s}` : `['${s}']`)).join('');

function importPath(fromFile) {
  let rel = path.relative(path.dirname(fromFile), keysFile).replace(/\\/g, '/').replace(/\.ts$/, '');
  if (!rel.startsWith('.')) rel = './' + rel;
  return rel;
}

// Files kept on literal keys: their spec renders right after a Leaflet map spec,
// and this builder shares one module registry per worker -- the map spec's module
// mock resets it and nulls the component's I18N import binding for the next file.
const SKIP = new Set(['photo-tooltip.component.ts']);

function listFiles(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules') listFiles(f, acc); }
    else if (/\.(ts|html)$/.test(e.name) && !/\.spec\.ts$/.test(e.name) && !SKIP.has(e.name)) acc.push(f);
  }
  return acc;
}

const PIPE_RE = /(['"])([^'"\n]+)\1(?=\s*\|\s*translate\b)/g;
const T_CALL_RE = /\.t\((['"])([^'"\n]+)\1/g;

let stat = { pipe: 0, tcall: 0, files: 0, imports: 0, fields: 0, unknown: new Set() };

function transform(content, isHtml) {
  let changed = content.replace(PIPE_RE, (m, _q, key) => {
    if (keys.has(key)) { stat.pipe++; return accessor(key); }
    stat.unknown.add(key); return m;
  });
  if (!isHtml) {
    changed = changed.replace(T_CALL_RE, (m, _q, key) => {
      if (keys.has(key)) { stat.tcall++; return `.t(${accessor(key)}`; }
      stat.unknown.add(key); return m;
    });
  }
  return changed;
}

function addImport(content, file) {
  if (/\bimport\s*\{[^}]*\bI18N\b[^}]*\}\s*from/.test(content)) return content;
  const imp = `import { I18N } from '${importPath(file)}';`;
  const lines = content.split('\n');
  let last = -1;
  for (let i = 0; i < lines.length; i++) if (/^\s*import\b.*from\s+['"].*['"];?\s*$/.test(lines[i])) last = i;
  if (last === -1) { stat.imports++; return imp + '\n' + content; }
  lines.splice(last + 1, 0, imp);
  stat.imports++;
  return lines.join('\n');
}

// Add `protected readonly I18N = I18N;` to EVERY @Component class in the file
// (handles multi-component files and decorators far from the class via a huge
// inline template). A class is a component when its nearest preceding decorator
// is @Component. Idempotent: skips a class that already has the field.
function exposeField(content) {
  const decos = ['@Component(', '@Injectable(', '@Directive(', '@Pipe(', '@NgModule('];
  let out = '';
  let last = 0;
  const re = /export class \w+[^{]*\{/g;
  let m;
  while ((m = re.exec(content)) !== null) {
    const insertAt = m.index + m[0].length;
    out += content.slice(last, insertAt);
    last = insertAt;
    const before = content.slice(0, m.index);
    const idx = decos.map((d) => before.lastIndexOf(d));
    const isComponent = idx[0] !== -1 && idx[0] === Math.max(...idx);
    const after = content.slice(insertAt, insertAt + 200);
    if (isComponent && !/readonly I18N = I18N/.test(after)) {
      out += '\n  protected readonly I18N = I18N;';
      stat.fields++;
    }
  }
  out += content.slice(last);
  return out;
}

// Map external templateUrl -> component .ts so html-only templates get the field.
const tsFiles = listFiles(srcRoot).filter((f) => f.endsWith('.ts'));
const htmlOwner = new Map();
for (const ts of tsFiles) {
  const c = fs.readFileSync(ts, 'utf8');
  const m = c.match(/templateUrl:\s*['"]([^'"]+)['"]/);
  if (m) htmlOwner.set(path.resolve(path.dirname(ts), m[1]), ts);
}

const files = listFiles(srcRoot);
const ownersNeedingField = new Set();

for (const file of files) {
  const orig = fs.readFileSync(file, 'utf8');
  const isHtml = file.endsWith('.html');
  let out = transform(orig, isHtml);
  if (out === orig) continue;
  stat.files++;

  if (isHtml) {
    fs.writeFileSync(file, out);
    const owner = htmlOwner.get(path.resolve(file));
    if (owner) ownersNeedingField.add(owner);
    continue;
  }

  out = addImport(out, file);
  // Inline-template component: original template pipe usage means the template references I18N.
  if (/\|\s*translate\b/.test(orig) && /@Component\(/.test(orig)) out = exposeField(out);
  fs.writeFileSync(file, out);
}

// External-template owners: ensure import + field.
for (const owner of ownersNeedingField) {
  let c = fs.readFileSync(owner, 'utf8');
  const before = c;
  c = addImport(c, owner);
  c = exposeField(c);
  if (c !== before) fs.writeFileSync(owner, c);
}

console.log(`files changed: ${stat.files}`);
console.log(`pipe rewrites: ${stat.pipe}, .t() rewrites: ${stat.tcall}`);
console.log(`imports added: ${stat.imports}, I18N fields added: ${stat.fields}`);
if (stat.unknown.size) {
  console.log(`UNKNOWN keys left untouched (${stat.unknown.size}):`);
  for (const k of [...stat.unknown].slice(0, 40)) console.log('  ', k);
}
