import type { Mock, MockInstance } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PhotoFaceLayerComponent, PhotoFaceRow, FACE_MENU_DELAY_MS } from './photo-face-layer.component';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { By } from '@angular/platform-browser';
import { PersonFaceMenuComponent } from '../persons/person-face-menu.component';

const ROWS: PhotoFaceRow[] = [
  { id: 1, face_index: 0, person_id: 5, person_name: 'Valerie', box: [0.1, 0.2, 0.3, 0.6] },
  { id: 2, face_index: 1, person_id: null, person_name: null, box: [0.5, 0.0, 0.6, 0.2] },
  // Untrusted dimensions: the server sends no box, so nothing is drawn.
  { id: 3, face_index: 2, person_id: null, person_name: null, box: null },
];

describe('PhotoFaceLayerComponent', () => {
  let fixture: ComponentFixture<PhotoFaceLayerComponent>;
  let component: PhotoFaceLayerComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockDialog: { open: Mock };
  let mockStore: { assignFace: Mock; createPerson: Mock; unassignPerson: Mock; reloadPersonOptions: Mock };
  let mockSnackBar: { open: Mock };
  let openSpy: MockInstance;
  let mockRouter: { navigate: Mock; url: string };

  async function render(rows: PhotoFaceRow[] = ROWS, width: number | null = 1000, height: number | null = 500) {
    mockApi.get.mockReturnValue(of({ faces: rows }));
    fixture = TestBed.createComponent(PhotoFaceLayerComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('path', '/p/a.jpg');
    fixture.componentRef.setInput('imageWidth', width);
    fixture.componentRef.setInput('imageHeight', height);
    fixture.componentRef.setInput('canEdit', true);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    openSpy = vi.spyOn(fixture.debugElement.query(By.directive(PersonFaceMenuComponent)).componentInstance as PersonFaceMenuComponent, 'open');
  }

  /** The face the shared menu was last opened on, null when it never was. */
  function menuFace(): { id: number } | null {
    const call = openSpy.mock.calls.at(-1);
    return call ? (call[0] as { face: { id: number } }).face : null;
  }

  /** Open the shared menu on face ``i`` the keyboard way, and hand it back. */
  function menuFor(i: number): PersonFaceMenuComponent {
    component.onFaceKey(component.faces()[i], new KeyboardEvent('keydown', { key: 'Enter' }));
    fixture.detectChanges();
    return fixture.debugElement.query(By.directive(PersonFaceMenuComponent)).componentInstance as PersonFaceMenuComponent;
  }

  /** Run ``fn`` under fake timers and let the delayed menu open fire. */
  function withMenuDelay(fn: () => void): void {
    vi.useFakeTimers();
    try {
      fn();
      vi.advanceTimersByTime(FACE_MENU_DELAY_MS);
    } finally {
      vi.useRealTimers();
    }
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(), post: vi.fn(() => of({})) };
    mockDialog = { open: vi.fn() };
    mockStore = {
      assignFace: vi.fn(async () => true),
      createPerson: vi.fn(async () => ({ id: 9, name: 'New', face_count: 1 })),
      unassignPerson: vi.fn(async () => undefined),
      reloadPersonOptions: vi.fn(async () => undefined),
    };
    mockSnackBar = { open: vi.fn() };
    mockRouter = { navigate: vi.fn(() => Promise.resolve(true)), url: '/photo?path=x' };
    TestBed.configureTestingModule({
      imports: [PhotoFaceLayerComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialog, useValue: mockDialog },
        { provide: GalleryStore, useValue: mockStore },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: Router, useValue: mockRouter },
        { provide: UserActivityJournal, useValue: { record: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
  });

  it('asks the server for the photo faces', async () => {
    await render();
    expect(mockApi.get).toHaveBeenCalledWith('/photo/faces', { path: '/p/a.jpg' });
  });

  it('draws each trusted face in the photo pixel frame', async () => {
    await render();
    const svg = fixture.nativeElement.querySelector('svg') as SVGElement;
    expect(svg.getAttribute('viewBox')).toBe('0 0 1000 500');
    const rects = [...fixture.nativeElement.querySelectorAll('rect[data-face]')] as SVGRectElement[];
    expect(rects.length).toBe(2);
    expect(['x', 'y', 'width', 'height'].map((a) => Math.round(Number(rects[0].getAttribute(a))))).toEqual([100, 100, 200, 200]);
  });

  it('labels a named face with its name and an unnamed one as unknown', async () => {
    await render();
    const labels = [...fixture.nativeElement.querySelectorAll('text')].map((t) => (t as SVGTextElement).textContent?.trim());
    expect(labels[0]).toBe('Valerie');
    expect(labels[1]).toBe('photo_faces.unknown');
  });

  it('puts the label inside a box that touches the top edge', async () => {
    await render();
    const [named, top] = component.faces();
    expect(named.labelY).toBeLessThan(named.y);
    expect(top.labelY).toBeGreaterThan(top.y);
  });

  it('boxes named faces in white and unnamed faces in red', async () => {
    await render();
    const rects = [...fixture.nativeElement.querySelectorAll('rect[data-face]')] as SVGRectElement[];
    expect(rects[0].getAttribute('stroke')).toBe('white');
    expect(rects[1].getAttribute('stroke')).toBe('#ef4444');
  });

  it('shows boxes only on hover by default, and always in always mode', async () => {
    await render();
    const rect = () => fixture.nativeElement.querySelector('rect[data-face]') as SVGRectElement;
    expect(rect().classList.contains('opacity-0')).toBe(true);

    fixture.componentRef.setInput('mode', 'always');
    fixture.detectChanges();

    expect(rect().classList.contains('opacity-0')).toBe(false);
    expect(rect().classList.contains('opacity-100')).toBe(true);
  });

  it('keeps the focused person boxed, thicker, without showAll', async () => {
    await render();
    fixture.componentRef.setInput('focusPersonIds', [5]);
    fixture.detectChanges();
    const [focused, other] = [...fixture.nativeElement.querySelectorAll('rect[data-face]')] as SVGRectElement[];
    expect(focused.getAttribute('stroke-width')).toBe('4');
    expect(focused.classList.contains('opacity-100')).toBe(true);
    expect(other.getAttribute('stroke-width')).toBe('2');
    expect(other.classList.contains('opacity-0')).toBe(true);
  });

  it('sets the face as its person picture', async () => {
    await render();
    await menuFor(0).usePicture();
    await fixture.whenStable();
    expect(mockApi.post).toHaveBeenCalledWith('/person/5/avatar', { face_id: 1 });
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
  });

  it('draws nothing without the photo dimensions', async () => {
    await render(ROWS, null, null);
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
  });

  it('read-only: an unnamed face opens a menu that says naming needs edition mode', async () => {
    await render();
    fixture.componentRef.setInput('canEdit', false);

    withMenuDelay(() => component.onFaceClick(component.faces()[1], new MouseEvent('click', { clientX: 5, clientY: 6, detail: 1 })));
    fixture.detectChanges();
    await fixture.whenStable();

    expect(menuFace()?.id).toBe(2);
    const items = [...document.querySelectorAll('.mat-mdc-menu-panel button')] as HTMLButtonElement[];
    expect(items.map((b) => b.textContent?.trim())).toEqual(['lock photo_faces.name_needs_edition']);
    expect(items[0].disabled).toBe(true);
  });

  it('read-only: a face with a person opens its menu with no edition hint', async () => {
    await render();
    fixture.componentRef.setInput('canEdit', false);

    withMenuDelay(() => component.onFaceClick(component.faces()[0], new MouseEvent('click', { clientX: 5, clientY: 6, detail: 1 })));
    fixture.detectChanges();
    await fixture.whenStable();

    const text = [...document.querySelectorAll('.mat-mdc-menu-panel button')].map((b) => b.textContent ?? '').join('|');
    expect(text).toContain('photo_faces.view_photos');
    expect(text).not.toContain('name_needs_edition');
  });

  it('opens the gallery on all photos of the face person, named or not', async () => {
    await render();
    menuFor(0).viewPhotos();
    await fixture.whenStable();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { queryParams: { person_id: '5' } });
  });

  it('moves a face to the chosen person, then reloads and tells the page', async () => {
    await render();
    const changed = vi.fn();
    component.changed.subscribe(changed);
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ kind: 'select', person: { id: 7, name: 'Peter' } }) });
    const invalidate = vi.spyOn(TestBed.inject(PersonFaceBoxesService), 'invalidate');

    await menuFor(0).changePerson();
    await fixture.whenStable();

    expect(mockStore.assignFace).toHaveBeenCalledWith(1, 7, '/p/a.jpg', 'Peter');
    expect(invalidate).toHaveBeenCalledWith('/p/a.jpg');
    expect(mockApi.get).toHaveBeenCalledTimes(2);
    expect(changed).toHaveBeenCalled();
  });

  it('names an unknown face as a new person', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ kind: 'create', name: 'Aunt May' }) });

    await menuFor(1).changePerson();
    await fixture.whenStable();

    expect(mockStore.createPerson).toHaveBeenCalledWith('Aunt May', [2], '/p/a.jpg');
  });

  it('changes nothing when the picker is cancelled', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of(undefined) });

    await menuFor(0).changePerson();
    await fixture.whenStable();

    expect(mockStore.assignFace).not.toHaveBeenCalled();
    expect(mockStore.createPerson).not.toHaveBeenCalled();
  });

  it('takes only the clicked face off its person', async () => {
    await render();
    const invalidate = vi.spyOn(TestBed.inject(PersonFaceBoxesService), 'invalidate');
    const changed = vi.fn();
    component.changed.subscribe(changed);
    await menuFor(0).notThisPerson();
    await fixture.whenStable();
    expect(mockApi.post).toHaveBeenCalledWith('/face/1/unassign');
    expect(invalidate).toHaveBeenCalledWith('/p/a.jpg');
    expect(mockStore.unassignPerson).not.toHaveBeenCalled();
    expect(changed).toHaveBeenCalled();
  });

  it('says so when taking a face off its person fails', async () => {
    await render();
    mockApi.post.mockReturnValue(throwError(() => new Error('down')));
    const changed = vi.fn();
    component.changed.subscribe(changed);
    await menuFor(0).notThisPerson();
    await fixture.whenStable();
    expect(mockSnackBar.open).toHaveBeenCalledWith('photo_faces.unassign_error', '', { duration: 3000 });
    expect(changed).not.toHaveBeenCalled();
  });

  it('opens find-more for the face person', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ added: 2 }) });

    await menuFor(0).findMore();
    await fixture.whenStable();

    expect(mockDialog.open.mock.calls[0][1].data).toEqual({ personId: 5, personName: 'Valerie' });
    expect(mockSnackBar.open).toHaveBeenCalled();
  });

  describe('gestures and keyboard', () => {
    const group = (i = 0) => fixture.nativeElement.querySelectorAll('g[role="button"]')[i] as SVGGElement;
    const pointer = (type: string, x: number, y: number, pointerType = 'mouse') =>
      new PointerEvent(type, { clientX: x, clientY: y, pointerType, bubbles: true });

    it('lets pointerdown and dblclick bubble to the zoom directive', async () => {
      await render();
      const host = fixture.nativeElement as HTMLElement;
      const seen: string[] = [];
      host.addEventListener('pointerdown', () => seen.push('pointerdown'));
      host.addEventListener('dblclick', () => seen.push('dblclick'));
      group().dispatchEvent(pointer('pointerdown', 10, 10));
      group().dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      expect(seen).toEqual(['pointerdown', 'dblclick']);
    });

    it('a drag that starts on a face pans instead of opening the menu', async () => {
      await render();
      group().dispatchEvent(pointer('pointerdown', 10, 10));
      group().dispatchEvent(new MouseEvent('click', { clientX: 40, clientY: 12, bubbles: true }));
      expect(menuFace()).toBeNull();
    });

    it('a click that stays put opens the menu, after the double-click window', async () => {
      await render();
      vi.useFakeTimers();
      try {
        group().dispatchEvent(pointer('pointerdown', 10, 10));
        group().dispatchEvent(new MouseEvent('click', { clientX: 12, clientY: 11, detail: 1, bubbles: true }));
        expect(menuFace()).toBeNull();
        vi.advanceTimersByTime(FACE_MENU_DELAY_MS);
        expect(menuFace()?.id).toBe(1);
      } finally {
        vi.useRealTimers();
      }
    });

    it('a double-click on a face opens no menu and reaches the zoom directive', async () => {
      await render();
      const seen: string[] = [];
      (fixture.nativeElement as HTMLElement).addEventListener('dblclick', () => seen.push('dblclick'));
      const click = (detail: number) => new MouseEvent('click', { clientX: 10, clientY: 10, detail, bubbles: true });
      vi.useFakeTimers();
      try {
        group().dispatchEvent(pointer('pointerdown', 10, 10));
        group().dispatchEvent(pointer('pointerup', 10, 10));
        group().dispatchEvent(click(1));
        vi.advanceTimersByTime(100);
        group().dispatchEvent(pointer('pointerdown', 10, 10));
        group().dispatchEvent(pointer('pointerup', 10, 10));
        group().dispatchEvent(click(2));
        group().dispatchEvent(new MouseEvent('dblclick', { clientX: 10, clientY: 10, detail: 2, bubbles: true }));
        vi.advanceTimersByTime(FACE_MENU_DELAY_MS * 2);
      } finally {
        vi.useRealTimers();
      }
      expect(menuFace()).toBeNull();
      expect(document.querySelector('.mat-mdc-menu-panel')).toBeNull();
      expect(seen).toEqual(['dblclick']);
    });

    it('keyboard focus has its own cue, even on a box already shown', async () => {
      await render();
      fixture.componentRef.setInput('mode', 'always');
      fixture.detectChanges();
      const face = fixture.nativeElement.querySelector('rect[data-face]') as SVGRectElement;
      expect(face.classList.contains('opacity-100')).toBe(true);
      expect(face.classList).toContain('group-focus-visible/face:stroke-[length:6px]');
      expect(face.classList).toContain('group-focus-visible/face:stroke-sky-400');
    });

    it('a tap on an invisible box opens nothing, and does once boxes are shown', async () => {
      await render();
      group().dispatchEvent(pointer('pointerdown', 10, 10, 'touch'));
      group().dispatchEvent(new MouseEvent('click', { clientX: 10, clientY: 10, bubbles: true }));
      expect(menuFace()).toBeNull();

      fixture.componentRef.setInput('mode', 'always');
      fixture.detectChanges();
      withMenuDelay(() => {
        group().dispatchEvent(pointer('pointerdown', 10, 10, 'touch'));
        group().dispatchEvent(new MouseEvent('click', { clientX: 10, clientY: 10, detail: 1, bubbles: true }));
      });
      expect(menuFace()?.id).toBe(1);
    });

    it('each face is a focusable button named after its person, or unknown', async () => {
      await render();
      expect(fixture.nativeElement.querySelector('svg').getAttribute('aria-hidden')).toBeNull();
      expect(group(0).getAttribute('tabindex')).toBe('0');
      expect(group(0).getAttribute('aria-label')).toBe('Valerie');
      expect(group(1).getAttribute('aria-label')).toBe('photo_faces.unknown');
    });

    it('Enter and Space open the face menu', async () => {
      await render();
      group(1).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      expect(menuFace()?.id).toBe(2);
      openSpy.mockClear();
      group(0).dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
      expect(menuFace()?.id).toBe(1);
    });

    it('dashes unnamed faces and outlines every stroke in black', async () => {
      await render();
      const [named, unnamed] = [...fixture.nativeElement.querySelectorAll('rect[data-face]')] as SVGRectElement[];
      expect(named.getAttribute('stroke-dasharray')).toBeNull();
      expect(unnamed.getAttribute('stroke-dasharray')).toBe('6 4');
      const outlines = [...fixture.nativeElement.querySelectorAll('rect:not([data-face])')] as SVGRectElement[];
      expect(outlines.length).toBe(2);
      expect(outlines.every((r) => r.getAttribute('stroke') === 'black' && r.getAttribute('stroke-width') === '4')).toBe(true);
    });
  });

  describe('off mode', () => {
    it('draws nothing, even the focused person, and leaves nothing to tab to or click', async () => {
      await render();
      fixture.componentRef.setInput('focusPersonIds', [5]);
      fixture.componentRef.setInput('mode', 'off');
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('svg')).toBeNull();
      expect(fixture.nativeElement.querySelector('[tabindex="0"]')).toBeNull();
    });

    it('drops a menu open still pending when the mode turns off', async () => {
      await render();
      vi.useFakeTimers();
      try {
        component.onFaceClick(component.faces()[0], new MouseEvent('click', { clientX: 1, clientY: 1, detail: 1 }));
        fixture.componentRef.setInput('mode', 'off');
        fixture.detectChanges();
        vi.advanceTimersByTime(FACE_MENU_DELAY_MS);
      } finally {
        vi.useRealTimers();
      }
      expect(menuFace()).toBeNull();
    });

    it('the focused person stays boxed in hover mode', async () => {
      await render();
      fixture.componentRef.setInput('focusPersonIds', [5]);
      fixture.detectChanges();
      expect((fixture.nativeElement.querySelector('rect[data-face]') as SVGRectElement).classList).toContain('opacity-100');
    });
  });
});
