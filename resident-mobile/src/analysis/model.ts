import type { Category, MetricKey, TimePoint } from '../api/types';
import { colors } from '../theme';

export const postures: { key: MetricKey; name: string }[] = [
  { key: 'neck_flexion_extension', name: 'Neck flexion / extension' },
  { key: 'shoulder_hiking', name: 'Shoulder hiking' },
  { key: 'forward_trunk_lean', name: 'Forward trunk lean' },
  { key: 'lateral_trunk_lean', name: 'Lateral trunk lean' },
];

const scoreColors: Record<number, string> = { 1: colors.green, 2: '#9A741E', 3: '#B85A29', 4: colors.red };
const shoulderColors: Record<string, string> = {
  Neutral: colors.green,
  'Unilateral Right Hiking': '#BA6922',
  'Unilateral Left Hiking': '#9A4717',
  'Bilateral Hiking': colors.red,
};

export function categoryColor(metric: MetricKey, category: Category) {
  if (category.rula_score !== null) return scoreColors[category.rula_score] ?? colors.muted;
  if (metric === 'lateral_trunk_lean' && category.rula_adjustment_present !== null) {
    return category.rula_adjustment_present ? colors.red : colors.green;
  }
  if (metric === 'shoulder_hiking') return shoulderColors[category.key] ?? colors.muted;
  return colors.muted;
}

export function categoryLabel(category: Category) {
  return category.rula_score === null ? category.label : `${category.label} · RULA ${category.rula_score}`;
}

export function formatPercent(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Number(value.toFixed(2))}%` : 'Unavailable';
}

export function formatTime(seconds: number, precision = 1) {
  const scale = 10 ** precision;
  const elapsed = Math.round(seconds * scale) / scale;
  const minutes = Math.floor(elapsed / 60).toString().padStart(2, '0');
  const remainder = (elapsed % 60).toFixed(precision).padStart(precision ? 3 + precision : 2, '0');
  return `${minutes}:${remainder}`;
}

export function formatValue(value: number | null | undefined, unit: string) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable';
  if (unit === 'degrees') return `${value.toFixed(2)}°`;
  return `${value.toFixed(2)}${unit.startsWith('%') ? '' : ' '}${unit}`;
}

export function orderedPoints(points: TimePoint[]) {
  return points.filter((point) => Number.isFinite(point.time_seconds))
    .sort((left, right) => left.time_seconds - right.time_seconds || left.frame - right.frame);
}

export function nearestPointIndex(points: TimePoint[], time: number) {
  if (!points.length) return -1;
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].time_seconds < time) low = middle + 1;
    else high = middle;
  }
  return low > 0 && time - points[low - 1].time_seconds <= points[low].time_seconds - time ? low - 1 : low;
}

export function categoryBands(points: TimePoint[]) {
  const bands: { key: string; start: number; end: number }[] = [];
  points.forEach((point, index) => {
    if (!point.category) return;
    const previous = points[index - 1];
    const next = points[index + 1];
    const start = previous ? (previous.time_seconds + point.time_seconds) / 2 : point.time_seconds;
    const end = next ? (point.time_seconds + next.time_seconds) / 2 : point.time_seconds;
    if (end <= start) return;
    const last = bands[bands.length - 1];
    if (last?.key === point.category && last.end === start) last.end = end;
    else bands.push({ key: point.category, start, end });
  });
  return bands;
}
