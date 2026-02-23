import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { StatsFiltersService } from './stats-filters.service';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';

describe('StatsCorrelationsTabComponent', () => {
  let component: StatsCorrelationsTabComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        StatsCorrelationsTabComponent,
        { provide: ApiService, useValue: { get: jest.fn(() => of({})) } },
        { provide: I18nService, useValue: { t: jest.fn((k: string) => k), currentLang: jest.fn(() => 'en') } },
        { provide: StatsFiltersService, useValue: { filterCategory: signal(''), dateFrom: signal(''), dateTo: signal('') } },
      ],
    });
    component = TestBed.inject(StatsCorrelationsTabComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
