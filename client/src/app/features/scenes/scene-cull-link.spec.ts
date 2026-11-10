import { sceneCullParams } from './scene-cull-link';

describe('sceneCullParams', () => {
  it('builds the /culling query string "Cull this scene" opens', () => {
    expect(sceneCullParams({ start: '2002:11:30 14:08:43', end: '2002:11:30 14:27:27' }, null)).toEqual({
      group_by: 'scene', album: undefined, from: '2002:11:30 14:08:43', to: '2002:11:30 14:27:27', scene: '30/11/2002 14:08',
    });
  });

  it('keeps the album the scene was listed in', () => {
    expect(sceneCullParams({ start: '2002:11:30 14:08:43', end: null }, '7')).toEqual({
      group_by: 'scene', album: '7', from: '2002:11:30 14:08:43', to: undefined, scene: '30/11/2002 14:08',
    });
  });
});
