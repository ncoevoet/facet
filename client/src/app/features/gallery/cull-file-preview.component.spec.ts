import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../core/services/i18n.service';
import { CullFilePreviewComponent } from './cull-file-preview.component';

describe('CullFilePreviewComponent', () => {
  function build(paths: string[]) {
    TestBed.configureTestingModule({
      imports: [CullFilePreviewComponent],
      providers: [{ provide: I18nService, useValue: {
        translations: () => ({}),
        t: (key: string, vars?: Record<string, string | number>) => `${key} ${JSON.stringify(vars ?? {})}`,
      } }],
    });
    const fixture = TestBed.createComponent(CullFilePreviewComponent);
    fixture.componentRef.setInput('paths', paths);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const button = (key: string) => [...root.querySelectorAll('button')]
      .find(el => el.textContent?.includes(`cull.file_preview.${key}`))!;
    return { fixture, root, button };
  }

  it('renders only 24 actual resolved files per page, including the final page and previous', () => {
    const paths = Array.from({ length: 49 }, (_, n) => `/photos/${n}.jpg`);
    const { fixture, root, button } = build(paths);
    expect(root.querySelectorAll('li')).toHaveLength(24);
    const url = new URL(root.querySelector('img')!.getAttribute('src')!, 'http://facet.test');
    expect(url.pathname).toBe('/thumbnail');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      path: '/photos/0.jpg', size: '320', v: '3', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
    });
    expect(button('previous').disabled).toBe(true);
    button('next').click(); fixture.detectChanges();
    expect(root.querySelector('img')?.alt).toBe('24.jpg');
    button('next').click(); fixture.detectChanges();
    expect(root.querySelectorAll('li')).toHaveLength(1);
    expect(root.querySelector('img')?.alt).toBe('48.jpg');
    expect(button('next').disabled).toBe(true);
    expect(root.textContent).toContain('"start":49,"end":49,"total":49');
    button('previous').click(); fixture.detectChanges();
    expect(root.querySelector('img')?.alt).toBe('24.jpg');
  });

  it('enlarges an image without changing the file list and returns to its trigger', async () => {
    const { fixture, root, button } = build(['/photos/été & #1.jpg']);
    const trigger = root.querySelector('li button') as HTMLButtonElement;
    trigger.click(); fixture.detectChanges();
    await fixture.whenStable();
    expect(document.activeElement).toBe(button('back'));
    const image = root.querySelector('figure img') as HTMLImageElement;
    expect(image.alt).toBe('été & #1.jpg');
    expect(image.getAttribute('src')).toContain('size=1920');
    expect(root.querySelector('figcaption')?.textContent).toBe('/photos/été & #1.jpg');
    expect(root.querySelectorAll('li')).toHaveLength(1);
    button('back').click(); fixture.detectChanges();
    expect(root.querySelector('figure')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('uses the authorized library identity for mapped thumbnails while displaying the affected disk file', () => {
    const { fixture, root } = build(['/disk/mapped.jpg']);
    fixture.componentRef.setInput('thumbnailPaths', { '/disk/mapped.jpg': '/remote/mapped.jpg' });
    fixture.detectChanges();
    const url = new URL(root.querySelector('li img')!.getAttribute('src')!, 'http://facet.test');
    expect(url.pathname).toBe('/thumbnail');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      path: '/remote/mapped.jpg', size: '320', v: '3', 'ngsw-bypass': '1', session: expect.stringMatching(/^[a-f0-9]{32}$/),
    });
    expect(root.querySelector('li p')?.textContent).toBe('/disk/mapped.jpg');
    (root.querySelector('li button') as HTMLButtonElement).click(); fixture.detectChanges();
    expect(root.querySelector('figure img')?.getAttribute('src')).toContain('path=%2Fremote%2Fmapped.jpg');
    expect(root.querySelector('figcaption')?.textContent).toBe('/disk/mapped.jpg');
  });

  it('keeps XMP and unavailable RAW companions visible without pretending they have a preview', () => {
    const { fixture, root } = build(['/p.JPG', '/p.CR3', '/p.XMP']);
    expect(root.querySelectorAll('li')).toHaveLength(3);
    expect(root.querySelectorAll('li img')).toHaveLength(2);
    expect(root.querySelectorAll('li')[2].textContent).toContain('cull.file_preview.sidecar');
    root.querySelectorAll('li img')[1].dispatchEvent(new Event('error')); fixture.detectChanges();
    expect(root.querySelectorAll('li img')).toHaveLength(1);
    expect(root.querySelectorAll('li')[1].textContent).toContain('p.CR3');
    expect(root.querySelectorAll('li')[1].textContent).toContain('cull.file_preview.unavailable');
  });

  it('reports large-image failure and resets pagination, errors and enlargement for a new preview', () => {
    const { fixture, root, button } = build(Array.from({ length: 25 }, (_, n) => `/p${n}.jpg`));
    button('next').click(); fixture.detectChanges();
    (root.querySelector('li button') as HTMLButtonElement).click(); fixture.detectChanges();
    root.querySelector('figure img')!.dispatchEvent(new Event('error')); fixture.detectChanges();
    expect(root.querySelector('figure')?.textContent).toContain('cull.file_preview.unavailable');
    fixture.componentRef.setInput('paths', ['/new.jpg']); fixture.detectChanges();
    expect(root.querySelector('figure')).toBeNull();
    expect(root.querySelector('li img')?.getAttribute('alt')).toBe('new.jpg');
    expect(button('previous').disabled).toBe(true);
  });
});
