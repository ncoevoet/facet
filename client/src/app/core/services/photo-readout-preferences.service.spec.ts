import { TestBed } from '@angular/core/testing';
import { PHOTO_READOUT_KEY, PhotoReadoutPreferences } from './photo-readout-preferences.service';

describe('PhotoReadoutPreferences', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.removeItem(PHOTO_READOUT_KEY);
  });

  it('shows the readout by default and restores either saved choice', () => {
    const preferences = TestBed.inject(PhotoReadoutPreferences);
    expect(preferences.visible()).toBe(true);
    for (const visible of [false, true]) {
      TestBed.inject(PhotoReadoutPreferences).setVisible(visible);
      TestBed.resetTestingModule();
      expect(TestBed.inject(PhotoReadoutPreferences).visible()).toBe(visible);
    }
  });

  it('keeps the default if browser storage is malformed or unreadable', () => {
    localStorage.setItem(PHOTO_READOUT_KEY, 'broken');
    expect(TestBed.inject(PhotoReadoutPreferences).visible()).toBe(true);
    TestBed.resetTestingModule();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(TestBed.inject(PhotoReadoutPreferences).visible()).toBe(true);
  });

  it('still applies the choice in this session when persistence is blocked', () => {
    const preferences = TestBed.inject(PhotoReadoutPreferences);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    preferences.setVisible(false);
    expect(preferences.visible()).toBe(false);
    preferences.setVisible(true);
    expect(preferences.visible()).toBe(true);
  });
});
