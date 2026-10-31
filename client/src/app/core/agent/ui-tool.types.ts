/**
 * Shared shapes of the agent UI-tool layer: the contract entries generated
 * from the server's `api/agent/ui_tools.py`, the result envelope both consumers
 * (the tab bridge and in-page WebMCP) receive, and the error type a handler
 * throws.
 */

/** The only error codes the bridge protocol lets a tab report; the server maps any other to `upstream_error`. */
export const UI_TOOL_ERROR_CODES = [
  'invalid_input', 'not_found', 'forbidden_level', 'no_active_view', 'upstream_error', 'too_large',
  'unsaved_decisions', 'navigation_refused', 'plan_changed', 'plan_load_failed', 'no_plan', 'modal_open', 'stack_mode_active',
] as const;

export type UiToolErrorCode = (typeof UI_TOOL_ERROR_CODES)[number];

export interface UiToolAnnotations {
  readOnlyHint: boolean;
  untrustedContentHint: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
}

/** The subset of JSON Schema the contract uses. */
export interface JsonSchema {
  type?: string | string[];
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  minItems?: number;
  maxItems?: number;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  default?: unknown;
  description?: string;
}

export interface UiToolContract {
  name: string;
  description: string;
  inputSchema: JsonSchema;
  annotations: UiToolAnnotations;
}

/** One row of the generated `actions` table: a job, the page facts it applies to, and its tools with their floors. */
export interface UiActionRow {
  id: string;
  summary: string;
  when: string[];
  tools: { name: string; required_level: string }[];
}

export interface UiToolContractFile {
  version: string;
  tools: UiToolContract[];
  error_codes: string[];
  actions: UiActionRow[];
  /** Server contract filter name -> the tab store's name (api/agent/ui_tools.py CONTRACT_TO_CLIENT_KEY). */
  filter_key_map: Record<string, string>;
  /** Store keys a smart album never persists (api/agent/ui_tools.py SMART_ALBUM_EXCLUDE_KEYS). */
  smart_album_exclude_keys: string[];
}

export type UiToolEnvelope =
  | { ok: true; data: unknown }
  | { ok: false; error: UiToolErrorCode; message: string };

export type UiToolHandler = (args: Record<string, unknown>) => Promise<unknown>;

export class UiToolError extends Error {
  constructor(readonly code: UiToolErrorCode, message: string) {
    super(message);
    this.name = 'UiToolError';
  }
}
