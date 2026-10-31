import { Injectable, Injector, OnDestroy, inject } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  BaseRouteReuseStrategy,
  DetachedRouteHandle,
  destroyDetachedRouteHandle,
  Router,
} from '@angular/router';

const ALBUM_PATH = 'album/:albumId';
export const GALLERY_PATHS: readonly string[] = ['', ALBUM_PATH];
export const PHOTO_PATH = 'photo';
const STACK_EDITOR_PATH = 'stacks/edit';

const isGallery = (route: ActivatedRouteSnapshot) => GALLERY_PATHS.includes(route.routeConfig?.path ?? '-');

// Reattaching avoids rebuilding the gallery DOM on return from a photo.
@Injectable()
export class GalleryReuseStrategy extends BaseRouteReuseStrategy implements OnDestroy {
  // The Router injects this strategy, so it can only be looked up lazily.
  private readonly injector = inject(Injector);
  private kept: { key: string; handle: DetachedRouteHandle } | null = null;

  private get router(): Router {
    return this.injector.get(Router);
  }

  // The gallery reads its album id once on init, so another album needs a fresh instance.
  override shouldReuseRoute(future: ActivatedRouteSnapshot, curr: ActivatedRouteSnapshot): boolean {
    if (future.routeConfig === curr.routeConfig && future.routeConfig?.path === ALBUM_PATH
      && future.paramMap.get('albumId') !== curr.paramMap.get('albumId')) return false;
    return super.shouldReuseRoute(future, curr);
  }

  override shouldDetach(route: ActivatedRouteSnapshot): boolean {
    const next = this.router.currentNavigation()?.finalUrl;
    const segments = next?.root.children['primary']?.segments.map(segment => segment.path) ?? [];
    return isGallery(route) && (segments[0] === PHOTO_PATH || segments.join('/') === STACK_EDITOR_PATH);
  }

  override store(route: ActivatedRouteSnapshot, handle: DetachedRouteHandle | null): void {
    if (!handle) {
      this.kept = null;
      return;
    }
    this.drop();
    this.kept = { key: this.keyOf(route), handle };
  }

  override shouldAttach(route: ActivatedRouteSnapshot): boolean {
    if (!this.kept) return false;
    if (isGallery(route) && this.isBackToKept(route)) return true;
    // Activation asks about the photo immediately after storing the gallery.
    if (![PHOTO_PATH, STACK_EDITOR_PATH].includes(route.routeConfig?.path ?? '')) this.drop();
    return false;
  }

  override retrieve(): DetachedRouteHandle | null {
    return this.kept?.handle ?? null;
  }

  private isBackToKept(route: ActivatedRouteSnapshot): boolean {
    const navigation = this.router.currentNavigation();
    const previous = navigation?.previousNavigation?.finalUrl?.root.children['primary']?.segments.map(segment => segment.path).join('/');
    return (navigation?.trigger === 'popstate' || previous === STACK_EDITOR_PATH)
      && this.keyOf(route) === this.kept?.key;
  }

  private keyOf(route: ActivatedRouteSnapshot): string {
    return this.router.serializeUrl(this.router.createUrlTree(
      ['/', ...route.url.map(s => s.path)], { queryParams: route.queryParams },
    ));
  }

  ngOnDestroy(): void {
    this.drop();
  }

  private drop(): void {
    if (this.kept) destroyDetachedRouteHandle(this.kept.handle);
    this.kept = null;
  }
}
