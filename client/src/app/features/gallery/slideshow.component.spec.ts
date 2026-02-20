import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { SlideshowComponent } from './slideshow.component';
import { GalleryStore } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';

describe('SlideshowComponent', () => {
  let component: SlideshowComponent;
  let mockStore: { slideshowActive: ReturnType<typeof signal<boolean>>; nextPage: jest.Mock };
  const mockI18n = { t: (key: string) => key };

  beforeEach(() => {
    jest.useFakeTimers();
    mockStore = {
      slideshowActive: signal(true),
      nextPage: jest.fn(() => Promise.resolve()),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: mockI18n },
      ],
    });

    component = TestBed.runInInjectionContext(() => new SlideshowComponent());
  });

  afterEach(() => {
    component.ngOnDestroy();
    jest.useRealTimers();
  });

  describe('initial state', () => {
    it('starts at index 0', () => {
      expect(component.currentIndex()).toBe(0);
    });

    it('starts playing', () => {
      expect(component.isPlaying()).toBe(true);
    });

    it('starts with duration 4s', () => {
      expect(component.duration()).toBe(4);
    });

    it('starts with progress 0', () => {
      expect(component.progress()).toBe(0);
    });
  });

  describe('currentPhoto()', () => {
    it('returns null when no photos', () => {
      expect(component.currentPhoto()).toBeNull();
    });
  });

  describe('togglePlay()', () => {
    it('pauses when playing', () => {
      expect(component.isPlaying()).toBe(true);
      component.togglePlay();
      expect(component.isPlaying()).toBe(false);
    });

    it('resumes when paused', () => {
      component.togglePlay(); // pause
      component.togglePlay(); // resume
      expect(component.isPlaying()).toBe(true);
    });
  });

  describe('close()', () => {
    it('sets slideshowActive to false on the store', () => {
      component.close();
      expect(mockStore.slideshowActive()).toBe(false);
    });
  });

  describe('onDurationChange()', () => {
    it('updates duration signal', () => {
      component.onDurationChange(8);
      expect(component.duration()).toBe(8);
    });

    it('resets progress to 0', () => {
      // Manually set progress > 0
      component['progress'].set(50);
      component.onDurationChange(6);
      expect(component.progress()).toBe(0);
    });
  });

  describe('timer progress', () => {
    it('progress advances each 100ms tick', () => {
      // afterNextRender fires in TestBed and starts the interval
      // Reset state for clean measurement
      component['clearTimerInterval']();
      component.progress.set(0);
      component['startInterval']();
      jest.advanceTimersByTime(100); // one tick with default 4s duration: +2.5%
      expect(component.progress()).toBeCloseTo(2.5, 1);
    });

    it('resets progress and stays at index 0 after full duration (no photos)', () => {
      // With 1s duration, each tick = 100/(1*10) = 10%, need 10 ticks
      component['clearTimerInterval']();
      component.progress.set(0);
      component.duration.set(1);
      component['startInterval']();
      jest.advanceTimersByTime(1000); // 10 ticks of 100ms
      expect(component.currentIndex()).toBe(0); // no photos → stays at 0
      expect(component.progress()).toBe(0);
    });
  });

  describe('next() and prev()', () => {
    it('next() resets progress', () => {
      component['progress'].set(50);
      component.next();
      expect(component.progress()).toBe(0);
    });

    it('prev() resets progress', () => {
      component['progress'].set(50);
      component.prev();
      expect(component.progress()).toBe(0);
    });

    it('prev() wraps to last index when at 0 with no photos', () => {
      // photos() is empty, so length - 1 = -1 → Math.max(0, -1) = 0
      component.prev();
      expect(component.currentIndex()).toBe(0);
    });
  });

  describe('keyboard handler', () => {
    it('Space key toggles play/pause', () => {
      const handler = component['onKeyDown'].bind(component);
      expect(component.isPlaying()).toBe(true);
      handler(new KeyboardEvent('keydown', { key: ' ' }));
      expect(component.isPlaying()).toBe(false);
    });

    it('Escape key closes the slideshow', () => {
      const handler = component['onKeyDown'].bind(component);
      handler(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(mockStore.slideshowActive()).toBe(false);
    });

    it('ArrowRight advances to next', () => {
      const handler = component['onKeyDown'].bind(component);
      component['progress'].set(30);
      handler(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      expect(component.progress()).toBe(0);
    });

    it('ArrowLeft goes to prev', () => {
      const handler = component['onKeyDown'].bind(component);
      component['progress'].set(30);
      handler(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
      expect(component.progress()).toBe(0);
    });
  });

  describe('ngOnDestroy()', () => {
    it('clears the interval', () => {
      component['startInterval']();
      const clearSpy = jest.spyOn(window, 'clearInterval');
      component.ngOnDestroy();
      expect(clearSpy).toHaveBeenCalled();
    });
  });
});
