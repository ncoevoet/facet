import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ServerToolRegistry } from '../../core/agent/server-tool-registry.service';
import { AgentBridgeService } from '../../core/agent/agent-bridge.service';
import { McpTokenCreated, McpTokenItem } from '../../core/api/types';
import { ConnectAssistantDialogComponent, TOKENS_POLL_MS } from './connect-assistant-dialog.component';

const TOKEN_ROW: McpTokenItem = {
  id: 7, name: 'Laptop', level: 'readonly', token_prefix: 'fct_ab12', created_at: '2026-09-03T10:00:00',
  last_used_at: null, revoked: 0, user_id: 'u',
};
const SECRET = 'fct_ab12SECRETSECRETSECRETSECRET';

describe('ConnectAssistantDialogComponent', () => {
  let fixture: ComponentFixture<ConnectAssistantDialogComponent>;
  let listMcpTokens: Mock;
  let createMcpToken: Mock;
  let revokeMcpToken: Mock;
  let multiUser: boolean;
  let edition: boolean;
  let loginRequired: boolean;
  let connected: ReturnType<typeof signal<boolean>>;
  let inpage: boolean;
  let optedIn: ReturnType<typeof signal<boolean>>;
  let setOptIn: Mock;

  const text = (): string => (fixture.nativeElement as HTMLElement).textContent ?? '';
  const query = <T extends HTMLElement>(selector: string): T | null => (fixture.nativeElement as HTMLElement).querySelector<T>(selector);
  const queryAll = <T extends HTMLElement = HTMLElement>(selector: string): T[] => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<T>(selector));
  const flush = async (): Promise<void> => {
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const create = async (): Promise<void> => {
    fixture = TestBed.createComponent(ConnectAssistantDialogComponent);
    fixture.detectChanges();
    await flush();
  };
  const promptValue = (): string => query<HTMLTextAreaElement>('[data-testid="prompt"]')?.value ?? '';
  const buttonByText = (label: string): HTMLButtonElement | undefined =>
    queryAll('button').find(b => b.textContent?.includes(label)) as HTMLButtonElement | undefined;

  beforeEach(() => {
    multiUser = false;
    edition = false;
    loginRequired = true;
    connected = signal(false);
    listMcpTokens = vi.fn(() => of({ tokens: [TOKEN_ROW] }));
    inpage = true;
    optedIn = signal(false);
    setOptIn = vi.fn((on: boolean) => optedIn.set(on));
    createMcpToken = vi.fn((body: { name: string; level: McpTokenItem['level'] }) =>
      of({ ...TOKEN_ROW, id: 8, name: body.name, level: body.level, token: SECRET } as McpTokenCreated));
    revokeMcpToken = vi.fn(() => of({ id: 7, ok: true }));
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { listMcpTokens, createMcpToken, revokeMcpToken } },
        { provide: AuthService, useValue: { isMultiUser: () => multiUser, isEdition: () => edition, loginPasswordRequired: () => loginRequired, status: () => ({ features: { mcp_inpage: inpage } }) } },
        { provide: I18nService, useValue: { locale: signal('en'), t: (key: string, vars?: Record<string, string>) => (vars ? `${key} ${Object.values(vars).join(' ')}` : key), translations: signal({}) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: AgentBridgeService, useValue: { tabId: 'tab123', connected } },
        { provide: ServerToolRegistry, useValue: { optedIn: optedIn, setOptIn } },
      ],
    });
  });

  it('lists tokens with the prefix only as a tooltip, with dates in the viewer language and no plaintext', async () => {
    await create();
    expect(queryAll('[data-testid="token-row"]')).toHaveLength(1);
    expect(query('[data-testid="token-row"] [title]')?.getAttribute('title')).toBe('fct_ab12…');
    expect(query('[data-testid="token-row"]')?.textContent).not.toContain('fct_ab12');
    expect(text()).toContain('3 Sept 2026');
    expect(query('[data-testid="reveal"]')).toBeNull();
    expect(query('[data-testid="prompt"]')).toBeNull();
    expect(text()).not.toContain('SECRET');
  });

  it('shows the per-browser in-page opt-in unchecked and persists a change through the registry', async () => {
    await create();
    const box = query<HTMLInputElement>('[data-testid="inpage-optin"] input')!;
    expect(box.checked).toBe(false);
    box.click();
    await flush();
    expect(setOptIn).toHaveBeenCalledWith(true);
    expect(query<HTMLInputElement>('[data-testid="inpage-optin"] input')!.checked).toBe(true);
  });

  it('hides the in-page opt-in when the server has the feature off', async () => {
    inpage = false;
    await create();
    expect(query('[data-testid="inpage-optin"]')).toBeNull();
  });

  it('shows the Manage tokens disclosure with the token count, and no tab id', async () => {
    await create();
    const summary = query('[data-testid="tokens-disclosure"] summary')!;
    expect(summary.textContent).toContain('dialog.connect_assistant.manage_tokens 1');
    expect(query('[data-testid="bridge-status"]')?.textContent).not.toContain('tab123');
  });

  it('offers only the readonly level to a single-user, non-edition session', async () => {
    await create();
    const options = queryAll('select[name="token-level"] option').map(o => o.textContent?.trim());
    expect(options).toEqual(['dialog.connect_assistant.level_readonly']);
  });

  it('adds "act as me" for multi-user accounts and "full editing" only for an edition session', async () => {
    multiUser = true;
    await create();
    expect(queryAll('select[name="token-level"] option')).toHaveLength(2);
    TestBed.resetTestingModule();
    multiUser = true;
    edition = true;
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { listMcpTokens, createMcpToken, revokeMcpToken } },
        { provide: AuthService, useValue: { isMultiUser: () => true, isEdition: () => true, loginPasswordRequired: () => true, status: signal({ features: { mcp_inpage: false } }) } },
        { provide: I18nService, useValue: { locale: signal('en'), t: (key: string, vars?: Record<string, string>) => (vars ? `${key} ${Object.values(vars).join(' ')}` : key), translations: signal({}) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: AgentBridgeService, useValue: { tabId: 'tab123', connected } },
        { provide: ServerToolRegistry, useValue: { optedIn: optedIn, setOptIn } },
      ],
    });
    await create();
    expect(queryAll('select[name="token-level"] option')).toHaveLength(3);
  });

  it('mints with the chosen level and shows one vendor-neutral prompt holding the token', async () => {
    await create();
    expect(query('input[name="token-name"]')).not.toBeNull();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = '  CI box ';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(createMcpToken).toHaveBeenCalledWith({ name: 'CI box', level: 'readonly' });
    const prompt = promptValue();
    expect(prompt).toContain(SECRET);
    expect(prompt).toContain(`${location.origin}/mcp`);
    expect(prompt).toContain(`Authorization: Bearer ${SECRET}`);
    expect(prompt).toContain('status');
    expect(prompt.toLowerCase()).not.toMatch(/claude|codex|cursor/);
    expect(query('input[name="token-name"]')).toBeNull();
    expect(query('[data-testid="token-value"]')).toBeNull();
    expect(listMcpTokens).toHaveBeenCalledTimes(2);
  });

  it('returns to the form on Done, clears every plaintext copy and focuses the name field', async () => {
    await create();
    await mintAs('x');
    expect(promptValue()).toContain(SECRET);
    buttonByText('dialog.connect_assistant.done')!.click();
    await flush();
    expect(query('[data-testid="prompt"]')).toBeNull();
    expect(queryAll<HTMLTextAreaElement>('textarea').every(t => !t.value.includes(SECRET))).toBe(true);
    expect(text()).not.toContain(SECRET);
    expect(document.activeElement).toBe(query('input[name="token-name"]'));
  });

  it('offers exactly one copy button on the prompt step', async () => {
    await create();
    await mintAs('x');
    expect(queryAll('button').filter(b => b.textContent?.includes('dialog.connect_assistant.copy'))).toHaveLength(1);
    expect(buttonByText('dialog.connect_assistant.copy_prompt')!.hasAttribute('aria-label')).toBe(false);
  });

  it('shows no plaintext token the next time the dialog opens', async () => {
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = 'x';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(promptValue()).toContain(SECRET);
    const instance = fixture.componentInstance as unknown as { createdToken: () => unknown };
    expect(instance.createdToken()).not.toBeNull();
    fixture.destroy();
    expect(instance.createdToken()).toBeNull();
    await create();
    expect(promptValue()).toBe('');
    expect(text()).not.toContain(SECRET);
    expect(text()).not.toMatch(/fct_[A-Za-z0-9]{12,}/);
  });

  it('keeps the tokens disclosure open across mint and Done once the user opened it', async () => {
    await create();
    const details = query<HTMLDetailsElement>('[data-testid="tokens-disclosure"]')!;
    details.open = true;
    details.dispatchEvent(new Event('toggle'));
    await mintAs('x');
    buttonByText('dialog.connect_assistant.done')!.click();
    await flush();
    expect(query<HTMLDetailsElement>('[data-testid="tokens-disclosure"]')!.open).toBe(true);
  });

  it('explains the token limit on a 412', async () => {
    createMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 412 })));
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = 'x';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_limit');
  });

  it('asks for confirmation, then revokes and removes the row', async () => {
    await create();
    buttonByText('dialog.connect_assistant.revoke')!.click();
    fixture.detectChanges();
    expect(revokeMcpToken).not.toHaveBeenCalled();
    expect(text()).toContain('dialog.connect_assistant.revoke_confirm');
    buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
    await flush();
    expect(revokeMcpToken).toHaveBeenCalledWith(7);
    expect(queryAll('[data-testid="token-row"]')).toHaveLength(0);
    expect(query('[data-testid="tokens-disclosure"] summary')?.textContent).toContain('manage_tokens 0');
  });

  it('names the revoked token in the snackbar', async () => {
    await create();
    buttonByText('dialog.connect_assistant.revoke')!.click();
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
    await flush();
    expect(TestBed.inject(MatSnackBar).open).toHaveBeenCalledWith('dialog.connect_assistant.revoked Laptop', '', { duration: 2000 });
  });

  it('shows an edition badge on edition tokens', async () => {
    listMcpTokens.mockReturnValue(of({ tokens: [{ ...TOKEN_ROW, level: 'edition' }] }));
    await create();
    expect(query('[data-testid="edition-badge"]')).not.toBeNull();
  });

  it('reflects the bridge status', async () => {
    await create();
    expect(query('[data-testid="bridge-status"]')?.textContent).toContain('dialog.connect_assistant.tab_not_connected');
    expect(query('[data-testid="bridge-status"]')?.textContent).not.toContain('tab123');
  });

  describe('grants the server will honour', () => {
    it('open install + edition session offers Full editing', async () => {
      loginRequired = false;
      edition = true;
      await create();
      const options = queryAll('select[name="token-level"] option').map(o => o.textContent?.trim());
      expect(options).toEqual(['dialog.connect_assistant.level_readonly', 'dialog.connect_assistant.level_edition']);
    });

    it('offers readonly only on an open install without an edition session', async () => {
      loginRequired = false;
      await create();
      expect(queryAll('select[name="token-level"] option')).toHaveLength(1);
    });

    it('shows the level the server granted when it capped the request', async () => {
      multiUser = true;
      edition = true;
      createMcpToken.mockReturnValueOnce(of({ ...TOKEN_ROW, id: 9, name: 'x', level: 'readonly', token: SECRET } as McpTokenCreated));
      await create();
      const select = query<HTMLSelectElement>('select[name="token-level"]')!;
      select.value = 'edition';
      select.dispatchEvent(new Event('change'));
      fixture.detectChanges();
      await mintAs('x');
      expect(createMcpToken).toHaveBeenCalledWith({ name: 'x', level: 'edition' });
      const granted = promptValue();
      expect(granted).toContain('dialog.connect_assistant.level_readonly (readonly)');
      expect(granted).not.toContain('level_edition');
    });
  });

  describe('failures', () => {
    it('reports a failed list load', async () => {
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      await create();
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.load_failed');
    });

    it('reports a non-412 mint failure as mint_failed', async () => {
      createMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
      await create();
      await mintAs('x');
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_failed');
    });

    it('reports a failed revoke as revoke_failed and keeps the row', async () => {
      revokeMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 404 })));
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      const alert = query('[role="alert"]')?.textContent;
      expect(alert).toContain('dialog.connect_assistant.revoke_failed');
      expect(alert).not.toContain('load_failed');
      expect(queryAll('[data-testid="token-row"]')).toHaveLength(1);
    });
  });

  describe('copy', () => {
    afterEach(() => {
      Reflect.deleteProperty(navigator, 'clipboard');
      delete (document as unknown as Record<string, unknown>)['execCommand'];
    });

    it('falls back to a hidden textarea when navigator.clipboard is unavailable', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      const execCommand = vi.fn(() => true);
      (document as unknown as Record<string, unknown>)['execCommand'] = execCommand;
      await create();
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await flush();
      expect(execCommand).toHaveBeenCalledWith('copy');
      expect(document.querySelector('textarea:not([data-testid="prompt"])')).toBeNull();
      expect(text()).toContain('dialog.connect_assistant.copied');
      expect(query('[data-testid="live-region"]')?.textContent).toContain('dialog.connect_assistant.copied');
    });

    it('opens the copy_failed snackbar and leaves copied false when writeText rejects', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.reject(new Error('denied'))) }, configurable: true });
      (document as unknown as Record<string, unknown>)['execCommand'] = vi.fn(() => false);
      await create();
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await flush();
      expect(TestBed.inject(MatSnackBar).open).toHaveBeenCalledWith('ui.copy_failed', '', { duration: 3000 });
      expect(text()).not.toContain('dialog.connect_assistant.copied');
      expect(buttonByText('dialog.connect_assistant.copy_prompt')).toBeDefined();
    });

    it('says nothing when both copy routes fail', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      (document as unknown as Record<string, unknown>)['execCommand'] = vi.fn(() => false);
      await create();
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await flush();
      expect(query('[data-testid="live-region"]')?.textContent).not.toContain('dialog.connect_assistant.copied');
    });
  });

  describe('accessibility', () => {
    it('keeps Create disabled until a name is typed', async () => {
      await create();
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(true);
      await mintAs('x', false);
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(false);
    });

    it('names the token on the Revoke buttons and the prompt on the Copy button', async () => {
      await create();
      expect(query('button[aria-label="dialog.connect_assistant.revoke_aria Laptop"]')).not.toBeNull();
      await mintAs('x');
      expect(buttonByText('dialog.connect_assistant.copy_prompt')).toBeDefined();
    });

    it('announces the mint in a polite live region and moves focus to the prompt heading', async () => {
      await create();
      await mintAs('x');
      const live = query('[data-testid="live-region"]')!;
      expect(live.getAttribute('aria-live')).toBe('polite');
      expect(live.textContent).toContain('token_created_announce');
      expect(document.activeElement?.id).toBe('connect-prompt-heading');
    });

    it('moves focus to the disclosure summary after a revoke', async () => {
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      expect(document.activeElement).toBe(query('[data-testid="tokens-disclosure"] summary'));
    });

    it('moves focus to the confirm button when Revoke turns into the confirm, and back to Revoke on cancel', async () => {
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      await flush();
      expect(document.activeElement).toBe(query('[data-testid="revoke-confirm-yes"]'));
      query<HTMLButtonElement>('button[aria-label^="dialog.connect_assistant.cancel_revoke_aria"]')!.click();
      await flush();
      expect(document.activeElement).toBe(query('button[aria-label^="dialog.connect_assistant.revoke_aria"]'));
    });

    it('re-announces a repeated copy by clearing the live region first', async () => {
      vi.useFakeTimers();
      try {
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
        await create();
        await mintAs('x');
        const live = query('[data-testid="live-region"]')!;
        const copyButton = buttonByText('dialog.connect_assistant.copy_prompt')!;
        copyButton.click();
        await flush();
        expect(live.textContent).toContain('dialog.connect_assistant.copied');
        copyButton.click();
        await flush();
        expect(live.textContent).toBe('');
        vi.advanceTimersByTime(150);
        fixture.detectChanges();
        expect(live.textContent).toContain('dialog.connect_assistant.copied');
      } finally {
        vi.useRealTimers();
        Reflect.deleteProperty(navigator, 'clipboard');
      }
    });

    it('names the Copy buttons by their visible "Copied" text while the copied state shows', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
      await create();
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await new Promise(resolve => setTimeout(resolve, 20));
      fixture.detectChanges();
      expect(buttonByText('dialog.connect_assistant.copied')).toBeDefined();
      expect(buttonByText('dialog.connect_assistant.copy_prompt')).toBeUndefined();
      Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('does not use the low-contrast amber-600 text', async () => {
      await create();
      await mintAs('x');
      expect(fixture.nativeElement.innerHTML).not.toContain('text-amber-600');
    });
  });

  async function mintAs(name: string, click = true): Promise<void> {
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = name;
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    if (!click) return;
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    await flush();
  }

  it('re-reads the token list when the bridge connects, so "Last used" is not stale', async () => {
    await create();
    expect(listMcpTokens).toHaveBeenCalledTimes(1);
    connected.set(true);
    await flush();
    await flush();
    expect(listMcpTokens).toHaveBeenCalledTimes(2);
  });

  describe('token management refused on an open install', () => {
    const forbidden = (): HttpErrorResponse => new HttpErrorResponse({ status: 403 });
    const REMOTE = 'dialog.connect_assistant.open_install_remote';

    beforeEach(() => {
      loginRequired = false;
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('replaces the form and the token list with the explanation after a refused list', async () => {
      listMcpTokens.mockReturnValue(throwError(forbidden));
      await create();
      expect(query('[data-testid="management-refused"]')?.textContent).toContain(REMOTE);
      expect(query('input[name="token-name"]')).toBeNull();
      expect(query('[data-testid="tokens-disclosure"]')).toBeNull();
      expect(query('[role="alert"]')?.textContent).not.toContain('load_failed');
    });

    it('stops the poll and the bridge-connect refresh after the first refusal', async () => {
      vi.useFakeTimers();
      listMcpTokens.mockReturnValue(throwError(forbidden));
      await create();
      expect(listMcpTokens).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 3);
      connected.set(true);
      fixture.detectChanges();
      await vi.advanceTimersByTimeAsync(0);
      expect(listMcpTokens).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    });

    it('explains a refused mint', async () => {
      createMcpToken.mockReturnValueOnce(throwError(forbidden));
      await create();
      await mintAs('x');
      expect(query('[data-testid="management-refused"]')?.textContent).toContain(REMOTE);
      expect(query('[data-testid="reveal"]')).toBeNull();
    });

    it('explains a refused revoke', async () => {
      revokeMcpToken.mockReturnValueOnce(throwError(forbidden));
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      expect(query('[data-testid="management-refused"]')?.textContent).toContain(REMOTE);
    });

    it('still reports the token limit on a 412', async () => {
      createMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 412 })));
      await create();
      await mintAs('x');
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_limit');
      expect(query('[data-testid="management-refused"]')).toBeNull();
    });

    it('keeps mint_failed for a 403 on an install with a password', async () => {
      loginRequired = true;
      createMcpToken.mockReturnValueOnce(throwError(forbidden));
      await create();
      await mintAs('x');
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_failed');
      expect(query('[data-testid="management-refused"]')).toBeNull();
    });

    it('keeps load_failed and revoke_failed for a 403 on a multi-user install', async () => {
      loginRequired = false;
      multiUser = true;
      listMcpTokens.mockReturnValue(throwError(forbidden));
      await create();
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.load_failed');
      expect(query('[data-testid="management-refused"]')).toBeNull();
    });
  });

  describe('token list polling', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('cancels overlapping reads on close and never restarts polling from late results', async () => {
      vi.useFakeTimers();
      await create();
      const pending: Subject<{ tokens: McpTokenItem[] }>[] = [];
      listMcpTokens.mockImplementation(() => {
        const response = new Subject<{ tokens: McpTokenItem[] }>();
        pending.push(response);
        return response;
      });
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 6);
      expect(pending).toHaveLength(6);
      fixture.destroy();
      expect(pending.every(response => !response.observed)).toBe(true);
      for (let i = 0; i < 5; i++) pending[i].error(new HttpErrorResponse({ status: 503 }));
      await vi.advanceTimersByTimeAsync(0);
      pending[5].next({ tokens: [TOKEN_ROW] });
      await vi.advanceTimersByTimeAsync(0);
      const callsAfterClose = listMcpTokens.mock.calls.length;
      listMcpTokens.mockReturnValue(of({ tokens: [TOKEN_ROW] }));
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS);
      expect(listMcpTokens.mock.calls.length).toBe(callsAfterClose);
      expect(pending.every(response => !response.observed)).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });

    it('starts when the dialog opens, keeps its cadence, and stops for good once it is destroyed', async () => {
      vi.useFakeTimers();
      await create();
      expect(listMcpTokens).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS - 1);
      expect(listMcpTokens).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(listMcpTokens).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 2);
      expect(listMcpTokens).toHaveBeenCalledTimes(4);
      fixture.destroy();
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 10);
      expect(listMcpTokens).toHaveBeenCalledTimes(4);
      expect(vi.getTimerCount()).toBe(0);
    });

    it('stays quiet when a background poll fails', async () => {
      vi.useFakeTimers();
      await create();
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS);
      fixture.detectChanges();
      expect(query('[role="alert"]')).toBeNull();
    });

    it('five consecutive quiet failures stop the blind poll and surface the error', async () => {
      vi.useFakeTimers();
      await create();
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503 })));
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 5);
      fixture.detectChanges();
      const calls = listMcpTokens.mock.calls.length;
      expect(query('[role="alert"]')).not.toBeNull();
      // The blind poll is stopped: no further calls ever fire.
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 5);
      expect(listMcpTokens.mock.calls.length).toBe(calls);
      fixture.destroy();
    });

    it('a good read after the cap clears the error and restarts the poll', async () => {
      vi.useFakeTimers();
      await create();
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503 })));
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 5);
      fixture.detectChanges();
      expect(query('[role="alert"]')).not.toBeNull();
      // The server is back; a mint's own refresh is the next read.
      listMcpTokens.mockReturnValue(of({ tokens: [TOKEN_ROW] }));
      const input = query<HTMLInputElement>('input[name="token-name"]');
      input!.value = 'back';
      input!.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.mint')!.click();
      await vi.advanceTimersByTimeAsync(0);
      fixture.detectChanges();
      expect(query('[role="alert"]')).toBeNull();
      const calls = listMcpTokens.mock.calls.length;
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS);
      expect(listMcpTokens.mock.calls.length).toBe(calls + 1);
      fixture.destroy();
    });

    it('a failed user-visible read shows the error but is not a poll strike', async () => {
      vi.useFakeTimers();
      await create();
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503 })));
      // Four quiet strikes, then a failing mint refresh: still four strikes,
      // so the fifth poll is the one that stops the polling.
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 4);
      const input = query<HTMLInputElement>('input[name="token-name"]');
      input!.value = 'x';
      input!.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.mint')!.click();
      await vi.advanceTimersByTimeAsync(0);
      const afterMint = listMcpTokens.mock.calls.length;
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS);
      expect(listMcpTokens.mock.calls.length).toBe(afterMint + 1);
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 2);
      expect(listMcpTokens.mock.calls.length).toBe(afterMint + 1);
      fixture.destroy();
    });

    it('a good poll re-arms the failure counter', async () => {
      vi.useFakeTimers();
      await create();
      // Four quiet failures (below the cap), a good poll re-arming the
      // counter, four more: never five CONSECUTIVE failures, so the poll
      // stays alive and no error surfaces.
      for (let i = 0; i < 4; i++) {
        listMcpTokens.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 503 })));
      }
      listMcpTokens.mockReturnValueOnce(of({ tokens: [TOKEN_ROW] }));
      for (let i = 0; i < 4; i++) {
        listMcpTokens.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 503 })));
      }
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS * 9);
      fixture.detectChanges();
      expect(query('[role="alert"]')).toBeNull();
      const calls = listMcpTokens.mock.calls.length;
      await vi.advanceTimersByTimeAsync(TOKENS_POLL_MS);
      expect(listMcpTokens.mock.calls.length).toBe(calls + 1);
      fixture.destroy();
    });
  });
});
