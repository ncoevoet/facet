import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { PhotoMetricSectionComponent } from './photo-metric-section.component';
import { I18nService } from '../../../core/services/i18n.service';
import { makePhoto } from '../../../../testing/photo.fixture';

describe('composition metric icons', () => {
  it('distinguishes composition, subject and form metrics while retaining their labels', () => {
    TestBed.configureTestingModule({ providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(PhotoMetricSectionComponent);
    fixture.componentRef.setInput('kind', 'composition');
    fixture.componentRef.setInput('histogramHeight', 80);
    fixture.componentRef.setInput('photo', makePhoto({ comp_score: 7, power_point_score: 7,
      leading_lines_score: 7, isolation_bonus: 7, subject_sharpness: 7, subject_prominence: 7,
      subject_placement: 7, bg_separation: 7, form_symmetry: 7, form_balance: 7,
      form_edge_entropy: 7, form_fractal: 7, color_harmony: 7 }));
    fixture.detectChanges();
    const rows = [...(fixture.nativeElement as HTMLElement).querySelectorAll('app-metric-score-row')];
    const icons = rows.map(row => row.querySelector('mat-icon')!.textContent!.trim());
    expect(icons).toHaveLength(13); expect(new Set(icons).size).toBe(13);
    expect(icons).not.toContain('analytics');
    expect(rows[0].textContent).toContain('tooltip.composition');
    expect(rows.at(-1)!.textContent).toContain('tooltip.color_harmony');
    expect(rows.every(row => row.querySelector('mat-icon')!.getAttribute('aria-hidden') === 'true')).toBe(true);
    fixture.destroy();
  });
});

describe('exif section rows', () => {
  function render(overrides: Parameters<typeof makePhoto>[0]): HTMLElement {
    TestBed.configureTestingModule({ providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}), locale: signal('en') } },
    ] });
    const fixture = TestBed.createComponent(PhotoMetricSectionComponent);
    fixture.componentRef.setInput('kind', 'exif');
    fixture.componentRef.setInput('histogramHeight', 80);
    fixture.componentRef.setInput('photo', makePhoto(overrides));
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }
  const text = (root: HTMLElement) => root.textContent!.replace(/\s+/g, ' ');

  it('renders every new row when the fields are set', () => {
    const root = render({ focal_length: 50, focal_length_35mm: 75, exposure_compensation: 0.7, flash: 1, white_balance: 1,
      metering_mode: 5, image_width: 6000, image_height: 4000, file_size: 5_000_000,
      path: '/photos/2024/IMG_1.jpg', artist: 'Jane Doe', copyright: '(c) 2024 Jane' });
    const t = text(root);
    for (const key of ['tooltip.focal_35mm', 'tooltip.exposure_compensation', 'tooltip.flash', 'tooltip.white_balance',
      'tooltip.metering', 'tooltip.dimensions', 'tooltip.file_size', 'tooltip.folder', 'tooltip.artist', 'tooltip.copyright']) {
      // A label key must match on its own: 'tooltip.flash' is also a prefix of the value 'tooltip.flash_fired'.
      expect(t, key).toMatch(new RegExp(`${key.replace('.', '\\.')}(?!_)`));
    }
    expect(t).toContain('75mm'); expect(t).toContain('+0.7 EV'); expect(t).toContain('tooltip.flash_fired');
    expect(t).toContain('tooltip.white_balance_manual'); expect(t).toContain('tooltip.metering_pattern');
    expect(t).toContain('6000 \u00d7 4000'); expect(t).toContain('24.0 MP'); expect(t).toMatch(/5\s?MB/);
    expect(t).toContain('Jane Doe'); expect(t).toContain('(c) 2024 Jane');
    expect(root.querySelector('[title="/photos/2024"]')!.textContent).toContain('/photos/2024');
  });

  it('renders none of them when null or undefined', () => {
    const root = render({ camera_model: 'X100V', focal_length: 23, path: '/a.jpg', image_width: null, image_height: null });
    const t = text(root);
    for (const key of ['focal_35mm', 'exposure_compensation', 'flash', 'white_balance', 'metering', 'file_size', 'artist', 'copyright']) {
      expect(t, key).not.toContain('tooltip.' + key);
    }
    expect(t).not.toContain('tooltip.dimensions');
  });

  it('renders none of them when undefined (a store copy that lacks the fields)', () => {
    const t = text(render({ camera_model: 'X100V', exposure_compensation: undefined, flash: undefined, file_size: undefined }));
    expect(t).not.toContain('tooltip.flash'); expect(t).not.toContain('tooltip.exposure_compensation'); expect(t).not.toContain('tooltip.file_size');
  });

  it('keeps meaningful zero values: flash 0 and 0 EV', () => {
    const t = text(render({ flash: 0, exposure_compensation: 0 }));
    expect(t).toContain('tooltip.flash_off'); expect(t).toContain('0 EV');
  });

  it('copies the folder path on click and confirms with a toast', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const open = vi.fn();
    TestBed.overrideProvider(MatSnackBar, { useValue: { open } });
    const button = render({ path: '/photos/2024/IMG_1.jpg' }).querySelector<HTMLButtonElement>('[data-copy-folder]')!;
    expect(button.getAttribute('aria-label')).toBe('tooltip.copy_folder: /photos/2024');
    button.click();
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    expect(writeText).toHaveBeenCalledWith('/photos/2024');
    expect(open.mock.calls[0][0]).toBe('notifications.folder_copied');
  });

  it('hides the 35 mm row when it equals the focal length', () => {
    expect(text(render({ focal_length: 35, focal_length_35mm: 35 }))).not.toContain('tooltip.focal_35mm');
  });
});
