import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal } from '@angular/core';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MatContextMenuTrigger, MatMenuModule } from '@angular/material/menu';
import { By } from '@angular/platform-browser';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { Photo } from '../../shared/models/photo.model';
import { Album } from '../../core/services/album.service';
import { ViewerConfig } from './gallery.store';
import {
  GalleryPhotoMenuComponent, PhotoMenuActionEvent, PhotoMenuAction, isSheetAction,
} from './gallery-photo-menu.component';

const FULL_CONFIG = {
  features: {
    show_similar_button: true, show_critique: true, show_embed_metadata: true, show_albums: true,
  },
  cull: { trash_available: true },
} as unknown as ViewerConfig;

function makePhoto(over: Partial<Photo> = {}): Photo {
  return {
    path: '/d/a.jpg', filename: 'a.jpg', is_favorite: false, is_rejected: false,
    unassigned_faces: 0, ...over,
  } as unknown as Photo;
}

@Component({
  imports: [GalleryPhotoMenuComponent, MatMenuModule],
  template: `
    <app-gallery-photo-menu
      #m
      [isEdition]="isEdition()"
      [config]="config()"
      [albums]="albums()"
      [downloadProfiles]="profiles()"
      [canCompare]="canCompare()"
      [viewScoped]="viewScoped()"
      [downloading]="downloading()"
      (action)="events.push($event); order.push('action')"
      (closed)="order.push('closed')"
    />
    <div id="trigger" [matContextMenuTriggerFor]="m.menu()" [matContextMenuTriggerData]="data()"></div>
  `,
})
class HostComponent {
  readonly isEdition = signal(true);
  readonly config = signal<ViewerConfig | null>(FULL_CONFIG);
  readonly albums = signal<Album[]>([{ id: 7, name: 'Album A' } as Album]);
  readonly profiles = signal<string[]>([]);
  readonly canCompare = signal(true);
  readonly viewScoped = signal(false);
  readonly downloading = signal(false);
  readonly data = signal<{ photo: Photo; bulk: boolean; index: number }>({
    photo: makePhoto(), bulk: false, index: 0,
  });
  readonly events: PhotoMenuActionEvent[] = [];
  readonly order: string[] = [];
}

describe('GalleryPhotoMenuComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;
  let overlay: HTMLElement;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: I18nService,
          useValue: {
            t: (key: string) => key,
            translations: signal<Record<string, unknown>>({}),
            lang: signal('en'),
          },
        },
      ],
    });
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
    overlay = TestBed.inject(OverlayContainer).getContainerElement();
  });

  afterEach(() => fixture.destroy());

  function openMenu(photo: Photo, bulk: boolean): MouseEvent {
    host.data.set({ photo, bulk, index: 0 });
    fixture.detectChanges();
    const ev = new MouseEvent('contextmenu', {
      button: 2, clientX: 10, clientY: 10, bubbles: true, cancelable: true,
    });
    fixture.nativeElement.querySelector('#trigger').dispatchEvent(ev);
    fixture.detectChanges();
    return ev;
  }

  function itemEls(): HTMLButtonElement[] {
    return [...overlay.querySelectorAll('.mat-mdc-menu-item')] as HTMLButtonElement[];
  }

  function labelOf(el: HTMLElement): string {
    const spans = el.querySelectorAll('.mat-mdc-menu-item-text > span');
    return (spans[spans.length - 1]?.textContent ?? el.textContent ?? '').trim();
  }

  function labels(): string[] {
    return itemEls().map(labelOf);
  }

  function find(label: string): HTMLButtonElement {
    const el = itemEls().find(e => labelOf(e) === label);
    if (!el) throw new Error(`no menu item "${label}" in [${labels().join(' | ')}]`);
    return el;
  }

  function pick(...path: string[]): void {
    for (const label of path) {
      find(label).click();
      fixture.detectChanges();
    }
  }

  describe('layout', () => {
    it('bulk shows the set and compare items and none of the single-photo ones', () => {
      openMenu(makePhoto(), true);
      const l = labels();
      expect(l).toContain(I18N.gallery.selection.mark_sequence);
      expect(l).toContain(I18N.gallery.selection.compare);
      expect(l).toContain(I18N.gallery.selection.copy_filenames);
      expect(l).not.toContain(I18N.shortcuts.open_detail);
      expect(l).not.toContain(I18N.similar.find_similar);
      expect(l).not.toContain(I18N.gallery.selection.copy_filename);
    });

    it('single shows Open and none of the bulk-only items', () => {
      openMenu(makePhoto(), false);
      const l = labels();
      expect(l).toContain(I18N.shortcuts.open_detail);
      expect(l).toContain(I18N.similar.find_similar);
      expect(l).toContain(I18N.gallery.selection.copy_filename);
      expect(l).not.toContain(I18N.gallery.selection.compare);
      expect(l).not.toContain(I18N.gallery.selection.mark_sequence);
      expect(l).not.toContain(I18N.gallery.selection.copy_filenames);
    });

    it('hides Compare when the selection cannot be compared', () => {
      host.canCompare.set(false);
      openMenu(makePhoto(), true);
      expect(labels()).not.toContain(I18N.gallery.selection.compare);
    });

    it('offers the edit-tags entry in bulk mode', () => {
      openMenu(makePhoto(), true);
      expect(labels()).toContain(I18N.gallery.selection.edit_tags);
    });

    it('does not offer the edit-tags entry on a single photo', () => {
      openMenu(makePhoto(), false);
      expect(labels()).not.toContain(I18N.gallery.selection.edit_tags);
    });

    it('hides the album submenu when albums are disabled', () => {
      host.config.set({ ...FULL_CONFIG, features: { ...FULL_CONFIG.features, show_albums: false } } as ViewerConfig);
      openMenu(makePhoto(), false);
      expect(labels()).not.toContain(I18N.albums.add_photos);
    });

    for (const bulk of [true, false]) {
      it(`without edition mode shows no mutating item (bulk=${bulk})`, () => {
        host.isEdition.set(false);
        openMenu(makePhoto({ unassigned_faces: 2 }), bulk);
        const l = labels();
        for (const hidden of [
          I18N.gallery.selection.favorite, I18N.gallery.selection.reject,
          I18N.rating.add_favorite, I18N.rating.mark_rejected, I18N.gallery.selection.rate,
          I18N.albums.add_photos, I18N.export.action, I18N.cull.action, I18N.cull.delete_action,
          I18N.photoCard.embed_to_file, I18N.manage_persons.assign_face,
          I18N.gallery.selection.mark_sequence, I18N.gallery.selection.edit_tags,
        ]) {
          expect(l).not.toContain(hidden);
        }
        expect(l).toContain(bulk ? I18N.gallery.selection.copy_filenames : I18N.gallery.selection.copy_filename);
        expect(l).toContain(I18N.gallery.selection.download);
        if (!bulk) {
          expect(l).toContain(I18N.shortcuts.open_detail);
          expect(l).toContain(I18N.similar.find_similar);
          expect(l).toContain(I18N.critique.title);
        }
      });
    }
  });

  describe('delete gating', () => {
    it('is absent when trash is unavailable', () => {
      host.config.set({ ...FULL_CONFIG, cull: { trash_available: false } } as unknown as ViewerConfig);
      openMenu(makePhoto(), false);
      expect(labels()).not.toContain(I18N.cull.delete_action);
    });

    it('is present for bulk under a path selection', () => {
      openMenu(makePhoto(), true);
      expect(find(I18N.cull.delete_action).disabled).toBe(false);
    });

    it('is hidden (not disabled) for bulk under view scope', () => {
      host.viewScoped.set(true);
      openMenu(makePhoto(), true);
      expect(labels()).not.toContain(I18N.cull.delete_action);
    });

    it('stays enabled for a single photo under view scope', () => {
      host.viewScoped.set(true);
      openMenu(makePhoto(), false);
      expect(find(I18N.cull.delete_action).disabled).toBe(false);
    });
  });

  describe('assign face', () => {
    it('is absent with no unassigned faces', () => {
      openMenu(makePhoto({ unassigned_faces: 0 }), false);
      expect(labels()).not.toContain(I18N.manage_persons.assign_face);
    });

    it('is present with unassigned faces', () => {
      openMenu(makePhoto({ unassigned_faces: 2 }), false);
      expect(labels()).toContain(I18N.manage_persons.assign_face);
    });
  });

  describe('favorite and reject labels follow the photo state', () => {
    it('offers to add when neither is set', () => {
      openMenu(makePhoto(), false);
      expect(labels()).toContain(I18N.rating.add_favorite);
      expect(labels()).toContain(I18N.rating.mark_rejected);
      expect(labels()).not.toContain(I18N.rating.remove_favorite);
    });

    it('offers to remove when both are set', () => {
      openMenu(makePhoto({ is_favorite: true, is_rejected: true }), false);
      expect(labels()).toContain(I18N.rating.remove_favorite);
      expect(labels()).toContain(I18N.rating.unmark_rejected);
      expect(labels()).not.toContain(I18N.rating.add_favorite);
    });
  });

  describe('downloading', () => {
    it('disables the bulk download item while a download runs', () => {
      host.downloading.set(true);
      openMenu(makePhoto(), true);
      expect(find(I18N.gallery.selection.download).disabled).toBe(true);
    });

    it('disables the download submenu trigger while a download runs', () => {
      host.downloading.set(true);
      host.profiles.set(['Darktable A']);
      openMenu(makePhoto(), false);
      expect(find(I18N.gallery.selection.download).disabled).toBe(true);
    });
  });

  describe('emitted actions', () => {
    const photo = makePhoto({ unassigned_faces: 1 });
    const cases: { name: string; bulk: boolean; path: string[]; expected: PhotoMenuAction; profiles?: string[] }[] = [
      { name: 'bulk favorite', bulk: true, path: [I18N.gallery.selection.favorite], expected: { kind: 'favorite' } },
      { name: 'bulk reject', bulk: true, path: [I18N.gallery.selection.reject], expected: { kind: 'reject' } },
      { name: 'bulk rate 5', bulk: true, path: [I18N.gallery.selection.rate, '★★★★★'], expected: { kind: 'rate', rating: 5 } },
      { name: 'bulk rate 0', bulk: true, path: [I18N.gallery.selection.rate, I18N.gallery.selection.clear], expected: { kind: 'rate', rating: 0 } },
      { name: 'bulk album', bulk: true, path: [I18N.albums.add_photos, 'Album A'], expected: { kind: 'album', albumId: 7 } },
      { name: 'bulk create album', bulk: true, path: [I18N.albums.add_photos, I18N.albums.create], expected: { kind: 'create-album' } },
      { name: 'bulk panorama', bulk: true, path: [I18N.gallery.selection.mark_sequence, I18N.gallery.selection.mark_panorama], expected: { kind: 'mark-panorama', sequenceKind: 'panorama' } },
      { name: 'bulk hdr panorama', bulk: true, path: [I18N.gallery.selection.mark_sequence, I18N.gallery.selection.mark_hdr_panorama], expected: { kind: 'mark-panorama', sequenceKind: 'hdr_panorama' } },
      { name: 'bulk bracket', bulk: true, path: [I18N.gallery.selection.mark_sequence, I18N.gallery.selection.mark_bracket], expected: { kind: 'mark-panorama', sequenceKind: 'bracket' } },
      { name: 'bulk edit tags', bulk: true, path: [I18N.gallery.selection.edit_tags], expected: { kind: 'tags' } },
      { name: 'bulk copy', bulk: true, path: [I18N.gallery.selection.copy_filenames], expected: { kind: 'copy' } },
      { name: 'bulk export', bulk: true, path: [I18N.export.action], expected: { kind: 'export' } },
      { name: 'bulk cull', bulk: true, path: [I18N.cull.action], expected: { kind: 'cull' } },
      { name: 'bulk delete', bulk: true, path: [I18N.cull.delete_action], expected: { kind: 'delete' } },
      { name: 'bulk compare', bulk: true, path: [I18N.gallery.selection.compare], expected: { kind: 'compare' } },
      { name: 'bulk download (no profiles)', bulk: true, path: [I18N.gallery.selection.download], expected: { kind: 'download', type: 'original' } },
      { name: 'bulk download original', bulk: true, profiles: ['P1'], path: [I18N.gallery.selection.download, I18N.download.type_original], expected: { kind: 'download', type: 'original' } },
      { name: 'bulk download profile', bulk: true, profiles: ['P1'], path: [I18N.gallery.selection.download, 'P1'], expected: { kind: 'download', type: 'darktable', profile: 'P1' } },
      { name: 'bulk download raw', bulk: true, profiles: ['P1'], path: [I18N.gallery.selection.download, I18N.download.type_raw], expected: { kind: 'download', type: 'raw' } },
      { name: 'single open', bulk: false, path: [I18N.shortcuts.open_detail], expected: { kind: 'open' } },
      { name: 'single similar color', bulk: false, path: [I18N.similar.find_similar, I18N.similar.mode_color], expected: { kind: 'similar', mode: 'color' } },
      { name: 'single similar visual', bulk: false, path: [I18N.similar.find_similar, I18N.similar.mode_visual], expected: { kind: 'similar', mode: 'visual' } },
      { name: 'single similar person', bulk: false, path: [I18N.similar.find_similar, I18N.similar.mode_person], expected: { kind: 'similar', mode: 'person' } },
      { name: 'single critique', bulk: false, path: [I18N.critique.title], expected: { kind: 'critique' } },
      { name: 'single embed', bulk: false, path: [I18N.photoCard.embed_to_file], expected: { kind: 'embed' } },
      { name: 'single assign face', bulk: false, path: [I18N.manage_persons.assign_face], expected: { kind: 'assign-face' } },
      { name: 'single toggle favorite', bulk: false, path: [I18N.rating.add_favorite], expected: { kind: 'toggle-favorite' } },
      { name: 'single toggle reject', bulk: false, path: [I18N.rating.mark_rejected], expected: { kind: 'toggle-reject' } },
      { name: 'single rate 3', bulk: false, path: [I18N.gallery.selection.rate, '★★★'], expected: { kind: 'rate', rating: 3 } },
      { name: 'single album', bulk: false, path: [I18N.albums.add_photos, 'Album A'], expected: { kind: 'album', albumId: 7 } },
      { name: 'single create album', bulk: false, path: [I18N.albums.add_photos, I18N.albums.create], expected: { kind: 'create-album' } },
      { name: 'single copy', bulk: false, path: [I18N.gallery.selection.copy_filename], expected: { kind: 'copy' } },
      { name: 'single export', bulk: false, path: [I18N.export.action], expected: { kind: 'export' } },
      { name: 'single cull', bulk: false, path: [I18N.cull.action], expected: { kind: 'cull' } },
      { name: 'single delete', bulk: false, path: [I18N.cull.delete_action], expected: { kind: 'delete' } },
      { name: 'single download profile', bulk: false, profiles: ['P1'], path: [I18N.gallery.selection.download, 'P1'], expected: { kind: 'download', type: 'darktable', profile: 'P1' } },
    ];

    for (const c of cases) {
      it(`emits ${c.name}`, () => {
        if (c.profiles) host.profiles.set(c.profiles);
        openMenu(photo, c.bulk);
        pick(...c.path);
        expect(host.events).toEqual([{ action: c.expected, photo, bulk: c.bulk }]);
      });
    }
  });

  describe('action timing', () => {
    it('emits the picked action only after the menu has reported closed', () => {
      openMenu(makePhoto(), false);
      pick(I18N.export.action);
      expect(host.order).toEqual(['closed', 'action']);
    });

    it('emits nothing when the menu closes without a pick', () => {
      openMenu(makePhoto(), false);
      (overlay.querySelector('.cdk-overlay-backdrop') as HTMLElement).click();
      fixture.detectChanges();
      expect(host.order).toEqual(['closed']);
    });
  });

  describe('dismissal', () => {
    it('suppresses the native menu on the backdrop and closes the photo menu', () => {
      openMenu(makePhoto(), false);
      expect(fixture.debugElement.query(By.directive(MatContextMenuTrigger))
        .injector.get(MatContextMenuTrigger).menuOpen).toBe(true);
      const backdrop = overlay.querySelector('.cdk-overlay-backdrop') as HTMLElement;
      expect(backdrop).not.toBeNull();
      const ev = new MouseEvent('contextmenu', { button: 2, bubbles: true, cancelable: true });
      backdrop.dispatchEvent(ev);
      fixture.detectChanges();
      expect(ev.defaultPrevented).toBe(true);
      expect(fixture.debugElement.query(By.directive(MatContextMenuTrigger))
        .injector.get(MatContextMenuTrigger).menuOpen).toBe(false);
    });

    it('leaves a contextmenu on an unrelated element alone', () => {
      const other = document.createElement('div');
      document.body.appendChild(other);
      const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
      other.dispatchEvent(ev);
      other.remove();
      expect(ev.defaultPrevented).toBe(false);
    });
  });

  describe('isSheetAction', () => {
    it('is true for bulk kinds and false for single-photo-only kinds', () => {
      expect(isSheetAction({ kind: 'favorite' })).toBe(true);
      expect(isSheetAction({ kind: 'tags' })).toBe(true);
      expect(isSheetAction({ kind: 'download', type: 'raw' })).toBe(true);
      expect(isSheetAction({ kind: 'open' })).toBe(false);
      expect(isSheetAction({ kind: 'toggle-favorite' })).toBe(false);
      expect(isSheetAction({ kind: 'similar', mode: 'color' })).toBe(false);
    });
  });
});
