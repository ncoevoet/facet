import { randomUuid } from '../../shared/utils/random-uuid';
import {
  EnvironmentInjector,
  Injectable,
  computed,
  createEnvironmentInjector,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { McpCallRequest, McpCallResponse, McpInpageLevel, McpInpageTool, McpInpageTools } from '../api/types';
import { LEVEL_TIERS, agentLevel } from './agent-level';
import { WebMcpDescriptor, registerWebMcpTools, toWebMcpDescriptor } from './webmcp-descriptor';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { AgentBridgeService } from './agent-bridge.service';
import { AssistantChangesService } from './assistant-changes.service';
import { WebMcpToolRegistry } from './webmcp-registry.service';

export const INPAGE_OPT_IN_KEY = 'facet_agent_inpage_tools';
export const SESSION_HEADER = 'X-Facet-Agent-Session';
const TIERS: readonly McpInpageLevel[] = LEVEL_TIERS;
const STRIPPED_ARGS = ['tab_id'] as const;
/** Wait before the single retry of a failed tool listing. */
export const INPAGE_RETRY_MS = 2000;

function readOptIn(): boolean {
  try {
    return localStorage.getItem(INPAGE_OPT_IN_KEY) === '1';
  } catch {
    return false;
  }
}

/** The caller's level from the cached auth status: edition when unlocked, user for a signed-in multi-user account, else readonly. */
export function inpageLevel(status: { authenticated: boolean; multi_user: boolean; edition_authenticated: boolean } | null): McpInpageLevel | null {
  return status?.authenticated ? agentLevel(status) : null;
}

/**
 * Registers the server's own read and write tools as in-page WebMCP tools, for a browser whose user
 * opted in. Each proxy POSTs `/api/mcp/call`, so there is one implementation of every tool, on the server.
 *
 * One child injector per level tier hangs off the session injector: unlocking edition adds the edition
 * child, locking destroys only it, and logout, the opt-in turning off or `features.mcp_inpage` going
 * false destroys all of them.
 */
@Injectable({ providedIn: 'root' })
export class ServerToolRegistry {
  private readonly auth = inject(AuthService);
  private readonly web = inject(AgentWebMcpService);
  private readonly ui = inject(WebMcpToolRegistry);
  private readonly http = inject(HttpClient);
  private readonly changes = inject(AssistantChangesService);
  private readonly bridge = inject(AgentBridgeService);

  /** Per-browser opt-in, default off. */
  readonly optedIn = signal(readOptIn());
  /** Random per tab, created on the first call: it only isolates confirmation nonces between this user's sessions. */
  private sessionId: string | null = null;
  private readonly children = new Map<McpInpageLevel, EnvironmentInjector>();
  private generation = 0;
  private parent: EnvironmentInjector | null = null;

  /** Level to register for, or null when nothing should load; re-evaluated only when this value changes. */
  private readonly plan = computed(() => {
    const status = this.auth.status();
    const wanted = !!status?.authenticated && status.features['mcp'] === true && status.features['mcp_inpage'] === true && this.optedIn();
    return wanted ? inpageLevel(status) : null;
  }, { equal: (a, b) => a === b });

  constructor() {
    effect(() => {
      const level = this.plan();
      const session = this.web.sessionInjector();
      untracked(() => void this.apply(session && level ? level : null, session));
    });
  }

  setOptIn(on: boolean): void {
    try {
      if (on) localStorage.setItem(INPAGE_OPT_IN_KEY, '1');
      else localStorage.removeItem(INPAGE_OPT_IN_KEY);
    } catch {
      // Storage may be blocked; the choice then lasts for this page only.
    }
    this.optedIn.set(on);
  }

  private async apply(level: McpInpageLevel | null, session: EnvironmentInjector | null, retried = false): Promise<void> {
    const generation = ++this.generation;
    if (!level || !session) {
      this.destroyTiers(0);
      this.parent = null;
      return;
    }
    if (this.parent !== session) {
      this.destroyTiers(0);
      this.parent = session;
    }
    const rank = TIERS.indexOf(level);
    // Lock: only the tiers above the new level go.
    this.destroyTiers(rank + 1);
    const missing = TIERS.slice(0, rank + 1).filter(tier => !this.children.has(tier));
    if (!missing.length) return;
    let listing: McpInpageTools;
    try {
      listing = await firstValueFrom(this.http.get<McpInpageTools>('/api/mcp/inpage_tools'));
    } catch (err) {
      console.warn('Facet: could not load the in-page assistant tools', err);
      // One retry, and only if nothing changed meanwhile; a later level or auth change starts afresh.
      if (!retried) {
        setTimeout(() => {
          if (generation === this.generation) void this.apply(level, session, true);
        }, INPAGE_RETRY_MS);
      }
      return;
    }
    for (const tier of missing) {
      // Logout, a lock or the opt-in turning off may have landed during any await above or below.
      if (this.superseded(generation, session)) return;
      const child = createEnvironmentInjector([], session);
      this.children.set(tier, child);
      const tools = listing.tools.filter(tool => tool.required_level === tier);
      await registerWebMcpTools(tools.map(tool => this.descriptor(tool)), child);
    }
  }

  private superseded(generation: number, session: EnvironmentInjector): boolean {
    return generation !== this.generation || this.parent !== session;
  }

  private destroyTiers(fromRank: number): void {
    for (const tier of TIERS.slice(fromRank)) {
      this.children.get(tier)?.destroy();
      this.children.delete(tier);
    }
  }

  private descriptor(tool: McpInpageTool): WebMcpDescriptor {
    const readOnly = tool.annotations.readOnlyHint === true;
    return toWebMcpDescriptor({
      name: tool.name,
      description: tool.description,
      inputSchema: this.stripSchema(tool.inputSchema),
      annotations: {
        readOnlyHint: readOnly,
        ...(readOnly ? {} : { consequentialHint: true }),
        untrustedContentHint: true,
      },
      execute: (args: unknown) => this.call(tool, args),
    });
  }

  private stripSchema(schema: Record<string, unknown>): Record<string, unknown> {
    const properties = { ...(schema['properties'] as Record<string, unknown> | undefined) };
    for (const key of STRIPPED_ARGS) delete properties[key];
    const required = Array.isArray(schema['required']) ? (schema['required'] as string[]).filter(k => !STRIPPED_ARGS.includes(k as 'tab_id')) : undefined;
    return { ...schema, properties, ...(required ? { required } : {}) };
  }

  /**
   * The proxy call. Deliberately not tied to the injector's abort signal: a lock destroys the edition
   * child while a dry-run-then-confirm may be in flight, and cancelling it would strand the user's intent.
   */
  private async call(tool: McpInpageTool, args: unknown): Promise<string> {
    const input = { ...((args && typeof args === 'object' ? args : {}) as Record<string, unknown>) };
    for (const key of STRIPPED_ARGS) delete input[key];
    const body: McpCallRequest = { tool: tool.name, arguments: input, tab_id: this.bridge.tabId };
    const properties = (tool.inputSchema['properties'] ?? {}) as Record<string, unknown>;
    if ('target' in properties && (input['target'] === 'selection' || input['target'] === 'view')) {
      // "selection" carries the tab's selection; "view" (create_album) the tab's open gallery view.
      const snapshot = input['target'] === 'view'
        ? await this.ui.execute('ui_get_gallery_view', { limit: 1 })
        : await this.ui.execute('ui_get_selection', {});
      if (!snapshot.ok) return JSON.stringify(snapshot);
      body.selection_snapshot = snapshot.data && typeof snapshot.data === 'object' ? snapshot.data as Record<string, unknown> : null;
    }
    const callId = randomUuid();
    try {
      const response = await firstValueFrom(this.http.post<McpCallResponse>('/api/mcp/call', body, {
        headers: new HttpHeaders({ [SESSION_HEADER]: this.sessionId ??= randomUuid() }),
      }));
      // The key is present only when a photo-changing write ran (even an ok:false outcome_unknown one).
      if ('changed_paths' in response) {
        const paths = response.changed_paths ?? null;
        this.changes.report({
          tool: tool.name,
          agentTool: tool.name,
          callId,
          ...(response.show_paths !== undefined ? { showPaths: response.show_paths } : {}),
          paths,
          count: response.changed ?? paths?.length ?? response.show_paths?.length ?? null,
        });
      }
      return JSON.stringify(response);
    } catch (err) {
      // A 401 already reached the interceptor (logout); a 403 just reports, without ending the session.
      const status = (err as { status?: number }).status;
      const code = status === 403 ? 'forbidden_level' : 'upstream_error';
      return JSON.stringify({ ok: false, error: code, message: `The server refused the call (${status ?? 'network error'}).` });
    }
  }
}
