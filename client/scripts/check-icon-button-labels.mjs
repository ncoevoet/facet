#!/usr/bin/env node
// Fails when an icon-only Material button (`mat-icon-button` / `matIconButton`)
// does not have an accessible name. Angular Material renders `<mat-icon>` with
// `aria-hidden="true"` internally and `matTooltip` is not an accessible name,
// so an unlabelled icon button is announced as just "button" by a screen
// reader. This is stronger than a presence check: `[attr.aria-label]="expr"`
// is only a real accessible name if `expr` cannot itself evaluate to an
// empty or whitespace-only string, so the guard also statically evaluates
// the binding expression for that shape.
//
// Button tags in this codebase routinely span several lines, so this walks
// the raw character stream tracking quote state to find each opening tag's
// real end (the unquoted `>`) rather than matching per line or stopping at
// the first `>`, which would also break on a `>` inside an attribute
// expression such as `(click)="x > y"`.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = process.env.ICON_BUTTON_LABELS_SRC_ROOT
  ? resolve(process.env.ICON_BUTTON_LABELS_SRC_ROOT)
  : join(fileURLToPath(new URL('.', import.meta.url)), '..', 'src', 'app');
const EXTENSIONS = new Set(['.html', '.ts']);
const ICON_BUTTON_MARKERS = ['mat-icon-button', 'matIconButton'];
const ARIA_LABEL_PATTERN = /(^|[^\w-])(aria-label|\[attr\.aria-label\])\s*=/;

function collectFiles(dir) {
  const entries = readdirSync(dir);
  const files = [];
  for (const entry of entries) {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      files.push(...collectFiles(fullPath));
    } else if (EXTENSIONS.has(extname(entry))) {
      files.push(fullPath);
    }
  }
  return files;
}

function findOpenTags(content) {
  const tags = [];
  let i = 0;
  const len = content.length;
  while (i < len) {
    if (content[i] !== '<') {
      i++;
      continue;
    }
    if (content.startsWith('<!--', i)) {
      const end = content.indexOf('-->', i);
      i = end === -1 ? len : end + 3;
      continue;
    }
    const tagNameMatch = /^<([a-zA-Z][a-zA-Z0-9-]*)/.exec(content.slice(i));
    if (!tagNameMatch) {
      i++;
      continue;
    }
    const start = i;
    let j = i + 1;
    let quote = null;
    while (j < len) {
      const ch = content[j];
      if (quote) {
        if (ch === quote) quote = null;
      } else if (ch === '"' || ch === "'" || ch === '`') {
        quote = ch;
      } else if (ch === '>') {
        break;
      }
      j++;
    }
    const end = Math.min(j + 1, len);
    tags.push({ text: content.slice(start, end), start });
    i = end;
  }
  return tags;
}

function isIconOnlyButton(tagText) {
  return ICON_BUTTON_MARKERS.some((marker) => {
    const idx = tagText.indexOf(marker);
    if (idx === -1) return false;
    const before = tagText[idx - 1];
    const after = tagText[idx + marker.length];
    const boundaryBefore = before === undefined || /[\s"'\[\]]/.test(before);
    // A marker can be the last thing before the tag closes, either
    // `<button mat-icon-button>` (boundary is `>`) or a self-closing
    // `<a mat-icon-button/>` (boundary is `/`) — both are common enough that
    // missing either silently exempted the tag from every check below.
    const boundaryAfter = after === undefined || /[\s"'=\[\]>/]/.test(after);
    return boundaryBefore && boundaryAfter;
  });
}

function lineNumberAt(content, index) {
  let line = 1;
  for (let k = 0; k < index; k++) {
    if (content[k] === '\n') line++;
  }
  return line;
}

// Extracts the aria-label attribute's raw value (the text between the
// quotes) from an opening tag's source text, along with whether it is a
// property binding (`[attr.aria-label]="expr"`) or a static attribute
// (`aria-label="text"`). Returns null when the tag has no such attribute.
function extractAriaLabelAttribute(tagText) {
  const match = ARIA_LABEL_PATTERN.exec(tagText);
  if (!match) return null;
  let i = match.index + match[0].length;
  while (i < tagText.length && /\s/.test(tagText[i])) i++;
  const quote = tagText[i];
  if (quote !== '"' && quote !== "'") return null;
  const start = i + 1;
  let j = start;
  while (j < tagText.length && tagText[j] !== quote) j++;
  return { isBinding: match[2].startsWith('['), value: tagText.slice(start, j) };
}

// A small recursive-descent parser over the subset of JS/Angular template
// expression syntax that appears in this codebase's aria-label bindings:
// string literals, `+` concatenation, `||`, `??`, `?:`, parens, and the
// Angular pipe operator `|`. Everything else (identifiers, member access,
// calls, object/array literals, template literals with interpolation) is
// opaque — we cannot know its value, so it is treated as never provably
// empty. This is a deliberate, documented limitation: the guard proves an
// expression CAN reach an empty string through a literal, not that it can
// never be empty at runtime.
function parseExpression(str) {
  let i = 0;
  const len = str.length;

  function skipWs() {
    while (i < len && /\s/.test(str[i])) i++;
  }

  function skipStringLiteral() {
    const quote = str[i];
    i++;
    while (i < len && str[i] !== quote) {
      if (str[i] === '\\') i++;
      i++;
    }
    if (str[i] === quote) i++;
  }

  function skipBalanced(open, close) {
    let depth = 0;
    do {
      if (str[i] === open) depth++;
      else if (str[i] === close) depth--;
      else if (str[i] === "'" || str[i] === '"' || str[i] === '`') {
        skipStringLiteral();
        continue;
      }
      i++;
    } while (i < len && depth > 0);
  }

  // Consumes a run of "opaque" content (identifiers, member access, calls,
  // numbers, `?.`) up to the next boundary token this parser cares about.
  function consumeOtherRun() {
    while (i < len) {
      const c = str[i];
      if (c === '?') {
        if (str[i + 1] === '.') {
          i += 2;
          continue;
        }
        break;
      }
      if (c === ':' || c === '+' || c === '|' || c === ')' || c === ']' || c === '}') break;
      if (c === '(') {
        skipBalanced('(', ')');
        continue;
      }
      if (c === '[') {
        skipBalanced('[', ']');
        continue;
      }
      if (c === '{') {
        skipBalanced('{', '}');
        continue;
      }
      if (c === "'" || c === '"' || c === '`') {
        skipStringLiteral();
        continue;
      }
      i++;
    }
  }

  function parsePrimary() {
    skipWs();
    const ch = str[i];
    if (ch === '(') {
      i++;
      const node = parseExpr();
      skipWs();
      if (str[i] === ')') i++;
      return node;
    }
    if (ch === "'" || ch === '"') {
      const quote = ch;
      i++;
      let value = '';
      while (i < len && str[i] !== quote) {
        if (str[i] === '\\') {
          value += str[i + 1];
          i += 2;
          continue;
        }
        value += str[i];
        i++;
      }
      if (str[i] === quote) i++;
      return { type: 'string', value };
    }
    if (ch === '`') {
      i++;
      let hasInterpolation = false;
      let value = '';
      while (i < len && str[i] !== '`') {
        if (str[i] === '$' && str[i + 1] === '{') {
          hasInterpolation = true;
          i += 2;
          let depth = 1;
          while (i < len && depth > 0) {
            if (str[i] === '{') depth++;
            else if (str[i] === '}') depth--;
            i++;
          }
          continue;
        }
        value += str[i];
        i++;
      }
      if (str[i] === '`') i++;
      return hasInterpolation ? { type: 'opaque' } : { type: 'string', value };
    }
    if (ch === '{') {
      skipBalanced('{', '}');
      return { type: 'opaque' };
    }
    if (ch === '[') {
      skipBalanced('[', ']');
      return { type: 'opaque' };
    }
    consumeOtherRun();
    return { type: 'opaque' };
  }

  function parsePipeArg() {
    parseTernary();
  }

  // The Angular pipe operator is the loosest-binding operator in this
  // subset. Once any top-level `|` is found, the piped value's emptiness is
  // unknowable (it depends on the pipe implementation), so the whole node
  // becomes opaque; the pipe name and any `:`-separated args are skipped.
  function parsePipe() {
    let node = parseTernary();
    skipWs();
    while (str[i] === '|' && str[i + 1] !== '|') {
      node = { type: 'opaque' };
      i++;
      skipWs();
      consumeOtherRun();
      skipWs();
      while (str[i] === ':') {
        i++;
        skipWs();
        parsePipeArg();
        skipWs();
      }
      skipWs();
    }
    return node;
  }

  function parseTernary() {
    const node = parseNullish();
    skipWs();
    if (str[i] === '?' && str[i + 1] !== '.' && str[i + 1] !== '?') {
      i++;
      skipWs();
      const thenNode = parseTernary();
      skipWs();
      if (str[i] === ':') {
        i++;
        skipWs();
        const elseNode = parseTernary();
        return { type: 'ternary', then: thenNode, else: elseNode };
      }
      return { type: 'opaque' };
    }
    return node;
  }

  function parseNullish() {
    let node = parseOr();
    skipWs();
    while (str[i] === '?' && str[i + 1] === '?') {
      i += 2;
      skipWs();
      const right = parseOr();
      node = { type: 'nullish', left: node, right };
      skipWs();
    }
    return node;
  }

  function parseOr() {
    let node = parseAdd();
    skipWs();
    while (str[i] === '|' && str[i + 1] === '|') {
      i += 2;
      skipWs();
      const right = parseAdd();
      // Only the rightmost operand determines whether `A || B` can reach an
      // empty result: `''` is falsy, so if the left side ever evaluates to
      // `''` the `||` itself falls through to the right side anyway.
      node = { type: 'or', right };
      skipWs();
    }
    return node;
  }

  function parseAdd() {
    const parts = [parsePrimary()];
    skipWs();
    while (str[i] === '+') {
      i++;
      skipWs();
      parts.push(parsePrimary());
      skipWs();
    }
    return parts.length === 1 ? parts[0] : { type: 'add', parts };
  }

  function parseExpr() {
    return parsePipe();
  }

  return parseExpr();
}

function isReachablyEmpty(node) {
  if (!node) return false;
  switch (node.type) {
    case 'string':
      return node.value.trim() === '';
    case 'add':
      return node.parts.every(isReachablyEmpty);
    case 'or':
      return isReachablyEmpty(node.right);
    case 'nullish':
      return isReachablyEmpty(node.left) || isReachablyEmpty(node.right);
    case 'ternary':
      return isReachablyEmpty(node.then) || isReachablyEmpty(node.else);
    default:
      return false;
  }
}

function findViolations(filePath) {
  const content = readFileSync(filePath, 'utf8');
  const violations = [];
  for (const tag of findOpenTags(content)) {
    if (!isIconOnlyButton(tag.text)) continue;
    const line = lineNumberAt(content, tag.start);
    const attr = extractAriaLabelAttribute(tag.text);
    if (!attr) {
      violations.push({ file: filePath, line, reason: 'no aria-label or [attr.aria-label]' });
      continue;
    }
    if (attr.isBinding) {
      if (isReachablyEmpty(parseExpression(attr.value))) {
        violations.push({
          file: filePath,
          line,
          reason: '[attr.aria-label] can evaluate to an empty or whitespace-only string',
        });
      }
    } else if (attr.value.trim() === '') {
      violations.push({ file: filePath, line, reason: 'aria-label is empty or whitespace-only' });
    }
  }
  return violations;
}

function main() {
  const files = collectFiles(SRC_ROOT);
  const violations = files.flatMap(findViolations);
  if (violations.length > 0) {
    console.error(`Found ${violations.length} icon-only button(s) without a reliable accessible name:`);
    for (const { file, line, reason } of violations) {
      console.error(`  ${file}:${line} — ${reason}`);
    }
    console.error(
      '\nAdd a [attr.aria-label] that cannot resolve to an empty string (reuse the [matTooltip] expression when one exists, and give every fallback branch real text).',
    );
    process.exit(1);
  }
  console.log('All icon-only buttons have a reliable accessible name.');
  process.exit(0);
}

main();
