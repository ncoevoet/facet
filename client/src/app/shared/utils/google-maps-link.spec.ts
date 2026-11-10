import { googleMapsSearchUrl, isResolvableMapsLink, parseGoogleMapsInput } from './google-maps-link';

// Same cases as tests/test_google_maps_link.py: the two parsers must agree.
const PIN_URL = 'https://www.google.com/maps/place/Pine+Valley/@32.8,-116.5,12z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d32.6064!4d-116.3239!16s';
const DMS_LAT = 32 + 36 / 60 + 23 / 3600;
const DMS_LNG = -(116 + 19 / 60 + 26 / 3600);

function expectPoint(text: string, lat: number, lng: number): void {
  const point = parseGoogleMapsInput(text);
  expect(point).not.toBeNull();
  expect(point!.lat).toBeCloseTo(lat, 9);
  expect(point!.lng).toBeCloseTo(lng, 9);
}

describe('parseGoogleMapsInput', () => {
  describe('free text', () => {
    it.each([
      ['32.6064, -116.3239', 32.6064, -116.3239],
      ['32.6064 -116.3239', 32.6064, -116.3239],
      ['  -33.8688,151.2093  ', -33.8688, 151.2093],
      ['+32.6064; -116.3239', 32.6064, -116.3239],
      [`32°36'23.0"N 116°19'26.0"W`, DMS_LAT, DMS_LNG],
      [`33°51'S, 151°12'E`, -(33 + 51 / 60), 151 + 12 / 60],
      ['32.6064° N, 116.3239° W', 32.6064, -116.3239],
      [`116°19'26"W 32°36'23"N`, DMS_LAT, DMS_LNG],
    ])('reads %s', (text, lat, lng) => expectPoint(text, lat, lng));

    it.each([
      '', 'Pine Valley', '91, 10', '-90.5, 0', '10, 180.1', '10, -181',
      `32°61'0"N 116°0'0"W`, `32°0'0"N 116°0'0"N`, '1, 2, 3', 'NaN, 1', '32.6064,', 'x'.repeat(3000),
    ])('refuses %s', text => expect(parseGoogleMapsInput(text)).toBeNull());
  });

  describe('URLs', () => {
    it.each([
      [PIN_URL, 32.6064, -116.3239],
      ['https://www.google.com/maps/@32.6064,-116.3239,15z', 32.6064, -116.3239],
      ['https://www.google.com/maps/@32.6064,-116.3239,500m/data=!3m1!1e3', 32.6064, -116.3239],
      ['https://maps.google.com/?q=32.6064,-116.3239', 32.6064, -116.3239],
      ['https://maps.google.com/maps?q=loc:32.6064+-116.3239&z=10', 32.6064, -116.3239],
      ['https://www.google.com/maps/search/?api=1&query=32.6064%2C-116.3239', 32.6064, -116.3239],
      ['https://maps.google.com/?ll=32.6064,-116.3239&z=14', 32.6064, -116.3239],
      ['https://www.google.com/maps/@?api=1&map_action=map&center=32.6064,-116.3239', 32.6064, -116.3239],
      ['https://www.google.com/maps?q=1.5,2.5&ll=3,4', 1.5, 2.5],
      ['https://www.google.com/maps/@5,6,10z?q=1,2', 1, 2],
      ['https://www.google.com/maps/search/32.6064,+-116.3239', 32.6064, -116.3239],
      [`https://www.google.com/maps/place/32%C2%B036'23.0%22N+116%C2%B019'26.0%22W/`, DMS_LAT, DMS_LNG],
      ['https://consent.google.com/m?continue=https://www.google.com/maps/%4032.6064,-116.3239,15z', 32.6064, -116.3239],
      ['https://www.google.com/maps/%4032.6064,-116.3239,15z?x=100%', 32.6064, -116.3239],
      ['https://www.google.com/maps/place/X/data=!3d1.5!4d2.5!3d3.5!4d4.5', 3.5, 4.5],
      ['https://www.google.com/maps/dir/?api=1&destination=32.6,-116.3', 32.6, -116.3],
      ['https://www.google.com/maps/search/?api=1&q=1,2&q=3,4', 3, 4],
    ])('reads %s', (url, lat, lng) => expectPoint(url, lat, lng));

    it('prefers the dropped pin over the @ viewport centre', () => {
      expect(parseGoogleMapsInput(PIN_URL)).toEqual({ lat: 32.6064, lng: -116.3239 });
    });

    it.each([
      'https://maps.app.goo.gl/AbCdEf123',
      'https://www.google.com/maps/place/Pine+Valley',
      'https://www.google.com/maps/@95,10,10z',
      'https://maps.google.com/?q=Pine+Valley',
    ])('finds no point in %s', url => expect(parseGoogleMapsInput(url)).toBeNull());
  });
});

describe('isResolvableMapsLink', () => {
  it.each([
    ['https://maps.app.goo.gl/x', true],
    ['http://goo.gl/maps/x', true],
    ['https://www.google.com/maps', true],
    ['https://maps.app.goo.gl:8443/x', false],
    ['https://user:pw@maps.app.goo.gl/x', false],
    ['https://evil.example/maps', false],
    ['https://maps.app.goo.gl.evil.example/x', false],
    ['ftp://goo.gl/x', false],
    ['32.6, -116.3', false],
  ])('%s -> %s', (url, ok) => expect(isResolvableMapsLink(url)).toBe(ok));
});

describe('googleMapsSearchUrl', () => {
  it('builds the keyless search URL with six decimals', () => {
    expect(googleMapsSearchUrl({ lat: 32.6064, lng: -116.3239 }))
      .toBe('https://www.google.com/maps/search/?api=1&query=32.606400,-116.323900');
  });
});
