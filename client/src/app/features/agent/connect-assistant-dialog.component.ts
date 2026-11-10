import { ChangeDetectionStrategy, Component, ElementRef, Injector, NgZone, OnDestroy, afterNextRender, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AgentBridgeService } from '../../core/agent/agent-bridge.service';
import { ServerToolRegistry } from '../../core/agent/server-tool-registry.service';
import { McpTokenItem } from '../../core/api/types';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';
import { copyText } from '../../shared/utils/clipboard';
import { buildAssistantPrompt } from './assistant-prompt';

/** Gap between clearing the live region and re-setting it, long enough for the empty text to render. */
const ANNOUNCE_GAP_MS = 100;
/** How often the token list is re-read while the dialog is open. */
export const TOKENS_POLL_MS = 15000;

type TokenLevel = McpTokenItem['level'];

interface LevelOption {
  value: TokenLevel;
  label: string;
}


@Component({
  selector: 'app-connect-assistant-dialog',
  standalone: true,
  imports: [FormsModule, DatePipe, MatDialogModule, MatButtonModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.dialog.connect_assistant.title | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 !pt-2">
      <p class="sr-only" role="status" aria-live="polite" data-testid="live-region">{{ liveMessage() }}</p>
      @if (error(); as message) {
        <p class="text-sm text-red-700 dark:text-red-400" role="alert">{{ message | translate }}</p>
      }
      @if (createdToken()) {
        <section class="flex flex-col gap-2 rounded-lg border border-amber-500/60 p-3" aria-labelledby="connect-prompt-heading" data-testid="reveal">
          <h3 #promptHeading id="connect-prompt-heading" tabindex="-1" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.prompt_heading | translate }}</h3>
          <p class="text-xs text-amber-800 dark:text-amber-300">{{ I18N.dialog.connect_assistant.prompt_warning | translate }}</p>
          <textarea readonly rows="18" class="w-full rounded bg-black/10 p-2 font-mono text-xs" [attr.aria-label]="I18N.dialog.connect_assistant.prompt_box_aria | translate" [value]="promptText()" data-testid="prompt"></textarea>
          <div class="flex items-center gap-2">
            <button mat-stroked-button type="button" (click)="copy(promptText())">
              {{ (copied() ? I18N.dialog.connect_assistant.copied : I18N.dialog.connect_assistant.copy_prompt) | translate }}
            </button>
            <button mat-flat-button type="button" (click)="done()">{{ I18N.dialog.connect_assistant.done | translate }}</button>
          </div>
        </section>
      } @else {
        @if (managementRefused()) {
          <p class="text-sm" role="alert" data-testid="management-refused">{{ I18N.dialog.connect_assistant.open_install_remote | translate }}</p>
        } @else {
        <p class="text-sm opacity-80">{{ I18N.dialog.connect_assistant.intro | translate }}</p>
        <div class="flex flex-col gap-3">
          <label class="flex flex-col gap-1 text-sm">
            <span>{{ I18N.dialog.connect_assistant.name_label | translate }}</span>
            <input #nameField class="h-9 rounded border border-current/30 bg-transparent px-3" maxlength="100" name="token-name"
                   [placeholder]="I18N.dialog.connect_assistant.name_placeholder | translate"
                   [ngModel]="name()" (ngModelChange)="name.set($event)" (keydown.enter)="mint()" />
          </label>
          <label class="flex flex-col gap-1 text-sm">
            <span>{{ I18N.dialog.connect_assistant.level_label | translate }}</span>
            <select class="h-9 rounded border border-current/30 bg-transparent px-2" name="token-level" [(ngModel)]="level">
              @for (option of levelOptions(); track option.value) {
                <option class="text-black" [value]="option.value">{{ option.label | translate }}</option>
              }
            </select>
          </label>
          <div>
            <button mat-flat-button type="button" [disabled]="!canMint()" (click)="mint()">
              {{ I18N.dialog.connect_assistant.mint | translate }}
            </button>
          </div>
        </div>
        }
        <p class="flex items-center gap-2 text-sm" data-testid="bridge-status">
          <mat-icon class="shrink-0 !w-4 !h-4 !text-[16px] !leading-4" [class.text-[var(--facet-positive)]]="bridgeConnected()" [class.opacity-60]="!bridgeConnected()">{{ bridgeConnected() ? 'link' : 'link_off' }}</mat-icon>
          <span>{{ bridgeStatusKey() | translate }}</span>
        </p>
        @if (inpageAvailable()) {
          <label class="flex items-start gap-2 text-sm" data-testid="inpage-optin">
            <input type="checkbox" class="mt-1" name="inpage-optin" [checked]="inpageOptIn()" (change)="setInpage($event)" />
            <span class="flex flex-col">
              <span>{{ I18N.dialog.connect_assistant.inpage_toggle | translate }}</span>
              <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.dialog.connect_assistant.inpage_hint | translate }}</span>
            </span>
          </label>
        }
        @if (!managementRefused()) {
        <details #tokensDetails data-testid="tokens-disclosure" [open]="tokensOpen()" (toggle)="tokensOpen.set(tokensDetails.open)">
          <summary #tokensSummary class="cursor-pointer py-1 text-sm font-medium">{{ I18N.dialog.connect_assistant.manage_tokens | translate: { count: tokens().length } }}</summary>
        <div class="flex flex-col gap-2 pt-2">
        @for (token of tokens(); track token.id) {
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-current/20 py-1 pl-3 pr-1 text-sm" data-testid="token-row">
            <span class="font-medium" [title]="token.token_prefix + '…'">{{ token.name }}</span>
            @if (token.level === 'edition') {
              <span class="rounded bg-amber-500/20 px-1.5 text-xs text-amber-800 dark:text-amber-300" data-testid="edition-badge">{{ I18N.dialog.connect_assistant.level_edition_badge | translate }}</span>
            }
            <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.dialog.connect_assistant.col_created | translate }} {{ token.created_at | date: 'dd/MM/yyyy' }}</span>
            <span class="text-xs text-[var(--mat-sys-on-surface-variant)]">
              {{ I18N.dialog.connect_assistant.col_last_used | translate }}
              {{ token.last_used_at ? (token.last_used_at | date: 'dd/MM/yyyy') : (I18N.dialog.connect_assistant.never_used | translate) }}
            </span>
            <span class="ml-auto flex items-center gap-1">
              @if (confirmRevokeId() === token.id) {
                <span class="text-xs">{{ I18N.dialog.connect_assistant.revoke_confirm | translate }}</span>
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.revoke_confirm_yes_aria | translate: { name: token.name }" data-testid="revoke-confirm-yes" (click)="revoke(token.id)">{{ I18N.dialog.connect_assistant.revoke_confirm_yes | translate }}</button>
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.cancel_revoke_aria | translate: { name: token.name }" (click)="cancelRevoke(token.id)">{{ I18N.dialog.cancel | translate }}</button>
              } @else {
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.revoke_aria | translate: { name: token.name }" [attr.data-revoke-id]="token.id" (click)="askRevoke(token.id)">{{ I18N.dialog.connect_assistant.revoke | translate }}</button>
              }
            </span>
          </div>
        } @empty {
          <p class="text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.dialog.connect_assistant.no_tokens | translate }}</p>
        }
        </div>
        </details>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ConnectAssistantDialogComponent implements OnDestroy {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly bridge = inject(AgentBridgeService);
  private readonly serverTools = inject(ServerToolRegistry);

  private readonly injector = inject(Injector);
  private readonly zone = inject(NgZone);
  private readonly promptHeading = viewChild<ElementRef<HTMLElement>>('promptHeading');
  private readonly nameField = viewChild<ElementRef<HTMLElement>>('nameField');
  private readonly tokensSummary = viewChild<ElementRef<HTMLElement>>('tokensSummary');
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly name = signal('');
  protected level: TokenLevel = 'readonly';
  protected readonly tokens = signal<McpTokenItem[]>([]);
  /** The just-minted plaintext. Held only here, cleared when the dialog closes; never stored or routed. */
  protected readonly createdToken = signal<{ token: string; level: TokenLevel } | null>(null);
  protected readonly busy = signal(false);
  protected readonly canMint = computed(() => this.name().trim().length > 0 && !this.busy());
  /** Spoken by the polite live region: the mint, and the copy, happen where a screen-reader user is not looking. */
  protected readonly liveMessage = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly confirmRevokeId = signal<number | null>(null);
  private pollTimer: ReturnType<typeof setInterval> | undefined;
  private announceTimer: ReturnType<typeof setTimeout> | undefined;
  protected readonly copied = signal(false);
  protected readonly tokensOpen = signal(false);
  /** Set by the first 403 on an open install: token management there is local-only, so stop asking and say why. */
  protected readonly managementRefused = signal(false);
  protected readonly inpageAvailable = computed(() => this.auth.status()?.features['mcp_inpage'] === true);
  protected readonly inpageOptIn = computed(() => this.serverTools.optedIn());
  protected readonly bridgeConnected = computed(() => this.bridge.connected());
  protected readonly bridgeStatusKey = computed(() =>
    this.bridgeConnected()
      ? this.I18N.dialog.connect_assistant.tab_connected
      : this.I18N.dialog.connect_assistant.tab_not_connected,
  );

  /**
   * Only the grants the server will honour: an open install holds `readonly` at most, `user` is a
   * multi-user account concept (a single password has no such rung), `edition` needs an edition session.
   */
  protected readonly levelOptions = computed<LevelOption[]>(() => {
    const options: LevelOption[] = [{ value: 'readonly', label: this.I18N.dialog.connect_assistant.level_readonly }];
    if (!this.auth.isMultiUser() && !this.auth.loginPasswordRequired() && !this.auth.isEdition()) return options;
    if (this.auth.isMultiUser()) options.push({ value: 'user', label: this.I18N.dialog.connect_assistant.level_user });
    if (this.auth.isEdition()) options.push({ value: 'edition', label: this.I18N.dialog.connect_assistant.level_edition });
    return options;
  });

  /** The level the server actually granted, which it may have capped below the one requested. */
  protected readonly createdLevelKey = computed(() => {
    const keys = this.I18N.dialog.connect_assistant;
    const byLevel: Record<TokenLevel, string> = { edition: keys.level_edition, user: keys.level_user, readonly: keys.level_readonly };
    return byLevel[this.createdToken()?.level ?? 'readonly'];
  });

  protected readonly promptText = computed(() => {
    const created = this.createdToken();
    return created
      ? buildAssistantPrompt((key, params) => this.i18n.t(key, params), {
        url: `${location.origin}/mcp`,
        token: created.token,
        levelLabel: this.i18n.t(this.createdLevelKey()),
        level: created.level,
      })
      : '';
  });

  constructor() {
    void this.refresh();
    // "Last used" moves when an assistant connects, so pick it up then and lightly while the dialog stays open.
    let wasConnected = this.bridgeConnected();
    effect(() => {
      const connected = this.bridgeConnected();
      if (connected && !wasConnected) untracked(() => void this.refresh(true));
      wasConnected = connected;
    });
    // Outside the zone: a repeating timer inside it would keep the app from ever reporting stable.
    this.zone.runOutsideAngular(() => {
      this.pollTimer = setInterval(() => void this.refresh(true), TOKENS_POLL_MS);
    });
  }

  ngOnDestroy(): void {
    clearInterval(this.pollTimer);
    clearTimeout(this.announceTimer);
    this.createdToken.set(null);
  }

  /** True (and the dialog switches to the explanation, with the poll stopped) for a 403 on an open install. */
  private refuseIfNotLocal(err: unknown): boolean {
    const openInstall = !this.auth.loginPasswordRequired() && !this.auth.isMultiUser();
    if (!openInstall || !(err instanceof HttpErrorResponse) || err.status !== 403) return false;
    this.managementRefused.set(true);
    this.error.set(null);
    clearInterval(this.pollTimer);
    return true;
  }

  private async refresh(quiet = false): Promise<void> {
    if (this.managementRefused()) return;
    try {
      this.tokens.set((await firstValueFrom(this.api.listMcpTokens())).tokens.filter(t => !t.revoked));
    } catch (err) {
      if (!this.refuseIfNotLocal(err) && !quiet) this.error.set(this.I18N.dialog.connect_assistant.load_failed);
    }
  }

  protected async mint(): Promise<void> {
    const name = this.name().trim();
    if (!name || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      const created = await firstValueFrom(this.api.createMcpToken({ name, level: this.level }));
      this.createdToken.set({ token: created.token, level: created.level });
      this.name.set('');
      this.announce(this.i18n.t(this.I18N.dialog.connect_assistant.token_created_announce, { name: created.name }));
      afterNextRender(() => this.promptHeading()?.nativeElement.focus(), { injector: this.injector });
      await this.refresh();
    } catch (err) {
      if (this.refuseIfNotLocal(err)) return;
      this.error.set(err instanceof HttpErrorResponse && err.status === 412
        ? this.I18N.dialog.connect_assistant.mint_limit
        : this.I18N.dialog.connect_assistant.mint_failed);
    } finally {
      this.busy.set(false);
    }
  }

  protected setInpage(event: Event): void {
    this.serverTools.setOptIn((event.target as HTMLInputElement).checked);
  }

  /** The journal is optional on the page: a failed list simply hides the section. */
  protected async revoke(id: number): Promise<void> {
    this.confirmRevokeId.set(null);
    const name = this.tokens().find(row => row.id === id)?.name ?? '';
    try {
      await firstValueFrom(this.api.revokeMcpToken(id));
      this.tokens.update(rows => rows.filter(row => row.id !== id));
      const message = this.i18n.t(this.I18N.dialog.connect_assistant.revoked, { name });
      this.snackBar.open(message, '', { duration: 2000 });
      this.announce(message);
      // The revoked row (and its focused button) is gone; land on the disclosure's summary rather than on <body>.
      afterNextRender(() => this.tokensSummary()?.nativeElement.focus(), { injector: this.injector });
    } catch (err) {
      if (!this.refuseIfNotLocal(err)) this.error.set(this.I18N.dialog.connect_assistant.revoke_failed);
    }
  }

  /**
   * Speak `message` through the polite live region. A region whose text does not change is not
   * re-announced, so a repeat of the current message clears it first and sets it a beat later.
   */
  private announce(message: string): void {
    clearTimeout(this.announceTimer);
    if (this.liveMessage() !== message) {
      this.liveMessage.set(message);
      return;
    }
    this.liveMessage.set('');
    this.announceTimer = setTimeout(() => this.liveMessage.set(message), ANNOUNCE_GAP_MS);
  }

  private focusInRow(selector: string): void {
    afterNextRender(() => this.host.nativeElement.querySelector<HTMLElement>(selector)?.focus(), { injector: this.injector });
  }

  /** Revoke turns into the confirm buttons, so the button that held focus is gone: move focus to the confirm. */
  protected askRevoke(id: number): void {
    this.confirmRevokeId.set(id);
    this.focusInRow('[data-testid="revoke-confirm-yes"]');
  }

  protected cancelRevoke(id: number): void {
    this.confirmRevokeId.set(null);
    this.focusInRow(`[data-revoke-id="${id}"]`);
  }

  /** Leave the prompt: drop the plaintext token and return to the form. */
  protected done(): void {
    this.createdToken.set(null);
    this.copied.set(false);
    afterNextRender(() => this.nameField()?.nativeElement.focus(), { injector: this.injector });
  }

  protected async copy(text: string): Promise<void> {
    if (!await copyText(text)) return;
    this.copied.set(true);
    this.announce(this.i18n.t(this.I18N.dialog.connect_assistant.copied));
    setTimeout(() => this.copied.set(false), 2000);
  }
}
