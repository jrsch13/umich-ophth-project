import { categoryBands, formatTime, nearestPointIndex, orderedPoints } from '../src/analysis/model';
import { httpsApiUrl } from '../src/config';

test('HTTPS configuration accepts a same-API prefix and disallows embedded credentials and insecure addresses', () => {
  expect(httpsApiUrl('https://station.example.test/api/')).toBe('https://station.example.test/api');
  expect(httpsApiUrl('http://station.example.test')).toBeNull();
  expect(httpsApiUrl('https://name:password@station.example.test')).toBeNull();
  expect(httpsApiUrl('https://station.example.test/api?key=value')).toBeNull();
  expect(httpsApiUrl('https://station-dev.example.edu:8443')).toBeNull();
});

test('nearest-point selection handles irregular sampling and category gaps', () => {
  const points = orderedPoints([
    { time_seconds: 7, frame: 7, category: 'neutral' },
    { time_seconds: 0, frame: 0, category: 'neutral' },
    { time_seconds: 2, frame: 2, category: null },
    { time_seconds: 10, frame: 10, category: 'extension' },
  ]);
  expect(nearestPointIndex(points, -1)).toBe(0);
  expect(nearestPointIndex(points, 4)).toBe(1);
  expect(nearestPointIndex(points, 7.1)).toBe(2);
  expect(nearestPointIndex(points, 40)).toBe(3);
  expect(categoryBands(points)).toEqual([
    { key: 'neutral', start: 0, end: 1 },
    { key: 'neutral', start: 4.5, end: 8.5 },
    { key: 'extension', start: 8.5, end: 10 },
  ]);
  expect(formatTime(59.96)).toBe('01:00.0');
});
