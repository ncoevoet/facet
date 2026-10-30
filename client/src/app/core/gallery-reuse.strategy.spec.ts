import { Component, OnDestroy } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, provideRouter, RouteReuseStrategy, Router } from '@angular/router';
import { filter, firstValueFrom } from 'rxjs';
import { RouterTestingHarness } from '@angular/router/testing';
import { authGuard } from './guards/auth.guard';
import { AuthService } from './services/auth.service';
import { GalleryReuseStrategy } from './gallery-reuse.strategy';

let destroyed = 0;

@Component({ template: 'gallery' })
class GalleryStub implements OnDestroy {
  ngOnDestroy(): void {
    destroyed++;
  }
}

@Component({ template: 'other' })
class OtherStub {}

describe('GalleryReuseStrategy', () => {
  let harness: RouterTestingHarness;
  let gallery: GalleryStub;

  beforeEach(async () => {
    destroyed = 0;
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: '', component: GalleryStub },
          { path: 'album/:albumId', component: GalleryStub },
          { path: 'photo', component: OtherStub },
          { path: 'stacks/edit', component: OtherStub },
          { path: 'login', component: OtherStub },
          { path: 'protected', component: OtherStub, canActivate: [authGuard] },
          { path: 'persons', component: OtherStub },
          { path: '**', redirectTo: '' },
        ]),
        provideLocationMocks(),
        { provide: AuthService, useValue: { status: () => ({ authenticated: false }) } },
        { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      ],
    });
    harness = await RouterTestingHarness.create();
    // Starts the router's popstate listener, which Location.back() needs.
    TestBed.inject(Router).initialNavigation();
    gallery = await harness.navigateByUrl('/', GalleryStub);
    await harness.navigateByUrl('/photo?path=a.jpg');
  });

  const back = async () => {
    const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
    TestBed.inject(Location).back();
    await done;
  };

  it('destroys the kept gallery when the application injector is destroyed', () => {
    TestBed.resetTestingModule();
    expect(destroyed).toBe(1);
  });

  it('reattaches the same gallery on a history back', async () => {
    await back();
    expect(harness.routeDebugElement?.componentInstance).toBe(gallery);
    expect(destroyed).toBe(0);
  });

  it('preserves the gallery instance and DOM through the stack editor Back route', async () => {
    const album = await harness.navigateByUrl('/album/42?sort=date', GalleryStub);
    const node = harness.routeNativeElement;
    const before = destroyed;
    await harness.navigateByUrl('/stacks/edit');
    expect(destroyed).toBe(before);
    await harness.navigateByUrl('/album/42?sort=date');
    expect(harness.routeDebugElement?.componentInstance).toBe(album);
    expect(harness.routeNativeElement).toBe(node);
    expect(destroyed).toBe(before);
  });

  it('reattaches the parked gallery on a history back from the stack editor', async () => {
    const album = await harness.navigateByUrl('/album/42?sort=date', GalleryStub);
    await harness.navigateByUrl('/stacks/edit');
    const before = destroyed;
    await back();
    expect(harness.routeDebugElement?.componentInstance).toBe(album);
    expect(destroyed).toBe(before);
  });

  it('destroys the parked gallery when the stack editor leaves for another page', async () => {
    await harness.navigateByUrl('/album/42?sort=date', GalleryStub);
    await harness.navigateByUrl('/stacks/edit');
    const before = destroyed;
    await harness.navigateByUrl('/persons');
    expect(destroyed).toBe(before + 1);
  });

  it('drops the parked gallery when stack Back targets another album', async () => {
    const album = await harness.navigateByUrl('/album/42?sort=date', GalleryStub);
    await harness.navigateByUrl('/stacks/edit');
    const before = destroyed;
    await harness.navigateByUrl('/album/43?sort=date');
    expect(harness.routeDebugElement?.componentInstance).not.toBe(album);
    expect(destroyed).toBe(before + 1);
  });

  it('builds a fresh gallery when the photo navigates to it instead', async () => {
    await TestBed.inject(Router).navigateByUrl('/');
    expect(harness.routeDebugElement?.componentInstance).not.toBe(gallery);
    expect(destroyed).toBe(1);
  });

  it('destroys the kept gallery when the photo leaves elsewhere', async () => {
    await harness.navigateByUrl('/persons');
    expect(destroyed).toBe(1);
  });

  it('keeps an album gallery through photo navigation and repeated Back and Forward', async () => {
    const album = await harness.navigateByUrl('/album/42?sort=date', GalleryStub);
    await harness.navigateByUrl('/photo?path=a.jpg');
    await harness.navigateByUrl('/photo?path=b.jpg');
    await back();
    await back();
    expect(harness.routeDebugElement?.componentInstance).toBe(album);
    const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
    TestBed.inject(Location).forward();
    await done;
    await back();
    expect(harness.routeDebugElement?.componentInstance).toBe(album);
  });

  it('builds a fresh gallery when the album id changes, and reuses it when only the query does', async () => {
    const three = await harness.navigateByUrl('/album/3', GalleryStub);
    const count = destroyed;
    const five = await harness.navigateByUrl('/album/5', GalleryStub);
    expect(five).not.toBe(three);
    expect(destroyed).toBe(count + 1);
    expect(await harness.navigateByUrl('/album/5?sort=date', GalleryStub)).toBe(five);
  });

  it('does not reattach a gallery with different query parameters', async () => {
    await harness.navigateByUrl('/?sort=date', GalleryStub);
    await harness.navigateByUrl('/photo?path=b.jpg');
    const kept = await harness.navigateByUrl('/?sort=rating', GalleryStub);
    await harness.navigateByUrl('/photo?path=c.jpg');
    const count = destroyed;
    const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
    TestBed.inject(Location).historyGo(-3);
    await done;
    expect(TestBed.inject(Router).url).toBe('/?sort=date');
    expect(harness.routeDebugElement?.componentInstance).not.toBe(kept);
    expect(destroyed).toBe(count + 1);
  });

  it('destroys a gallery on a guard redirect away from the photo', async () => {
    const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd && e.urlAfterRedirects === '/login')));
    await harness.navigateByUrl('/protected');
    await done;
    expect(TestBed.inject(Router).url).toBe('/login');
    expect(destroyed).toBe(1);
  });

  it('builds a fresh gallery after a wildcard redirect from the photo', async () => {
    await harness.navigateByUrl('/missing');
    expect(harness.routeDebugElement?.componentInstance).not.toBe(gallery);
    expect(destroyed).toBe(1);
  });
});
