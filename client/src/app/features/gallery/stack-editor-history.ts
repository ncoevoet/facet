import { Router } from '@angular/router';
import { STACK_MIN_MEMBERS, STACK_MAX_MEMBERS } from './stack-limits';

export const STACK_EDITOR_HISTORY = 'facetStackEditor';
export interface StackEditorHistory {
  version: 1;
  identity: string;
  paths: string[];
  activePath?: string;
  returnUrl: string;
}

/** Keep the exact query/fragment, but admit only the actual gallery routes. */
export function stackEditorReturnUrl(router: Router, value: unknown): string {
  if (typeof value !== 'string') return '/';
  try {
    if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/';
    const decoded = decodeURIComponent(value.split(/[?#]/)[0]);
    if (decoded.startsWith('//') || decoded.includes('\\') || /%2f|%5c/i.test(value.split(/[?#]/)[0])) return '/';
    const root = router.parseUrl(value).root.children;
    const primary = root['primary'];
    if (Object.keys(root).some(key => key !== 'primary') || primary && (Object.keys(primary.children).length
      || primary.segments.some(segment => Object.keys(segment.parameters).length)
      || !(primary.segments.length === 0 || primary.segments.length === 2 && primary.segments[0].path === 'album'
        && /^\d+$/.test(primary.segments[1].path)))) return '/';
    decodeURIComponent(value);
    return value;
  } catch { return '/'; }
}

/** Browser history is untrusted input; server preview still authorizes every path. */
export function readStackEditorHistory(value: unknown, identity: string, router: Router): StackEditorHistory | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const state = value as Record<string, unknown>;
  if (Object.keys(state).some(key => !['version', 'identity', 'paths', 'activePath', 'returnUrl'].includes(key))
    || state['version'] !== 1 || state['identity'] !== identity || !Array.isArray(state['paths'])
    || state['paths'].length < STACK_MIN_MEMBERS || state['paths'].length > STACK_MAX_MEMBERS
    || state['paths'].some(path => typeof path !== 'string' || path.trim().length === 0)
    || new Set(state['paths']).size !== state['paths'].length
    || state['activePath'] !== undefined && !state['paths'].includes(state['activePath'])
    || typeof state['returnUrl'] !== 'string') return null;
  return { version: 1, identity, paths: [...state['paths']], activePath: state['activePath'] as string | undefined,
    returnUrl: stackEditorReturnUrl(router, state['returnUrl']) };
}
