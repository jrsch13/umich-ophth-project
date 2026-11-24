import { arc, pie, type PieArcDatum } from 'd3-shape';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

import { categoryColor, categoryLabel, formatPercent } from '../analysis/model';
import type { PostureSummary } from '../api/types';
import { colors, common } from '../theme';

export type Slice = { label: string; percent: number | null; color: string };

export function Donut({ slices, size }: { slices: Slice[]; size: number }) {
  const radius = size / 2 - 2;
  const visible = slices.filter(({ percent }) => percent !== null && Number.isFinite(percent) && percent > 0);
  const segments = pie<Slice>().sort(null).value((slice) => slice.percent ?? 0)(visible);
  const path = arc<PieArcDatum<Slice>>().innerRadius(radius * 0.71).outerRadius(radius);

  return (
    <Svg width={size} height={size} accessible={false} importantForAccessibility='no-hide-descendants'>
      <G x={size / 2} y={size / 2}>
        <Circle r={radius * 0.855} fill='none' stroke={colors.softLine} strokeWidth={radius * 0.29} />
        {segments.map((segment) => <Path key={segment.data.label} d={path(segment) ?? undefined} fill={segment.data.color} />)}
      </G>
    </Svg>
  );
}

export function Legend({ slices }: { slices: Slice[] }) {
  return (
    <View style={styles.legend}>
      {slices.map((slice) => (
        <View key={slice.label} style={styles.legendRow}>
          <View style={[styles.swatch, { backgroundColor: slice.color }]} />
          <Text style={styles.label}>{slice.label}</Text>
          <Text style={[styles.percent, common.number]}>{formatPercent(slice.percent)}</Text>
        </View>
      ))}
    </View>
  );
}

export function CategoryChart({ summary }: { summary: PostureSummary }) {
  const slices = summary.category_distribution.map((category) => ({
    label: categoryLabel(category),
    percent: category.percent_of_valid_time,
    color: categoryColor(summary.metric, category),
  }));

  return (
    <View style={[common.card, styles.card]}>
      <Text accessibilityRole='header' style={common.sectionTitle}>RULA category breakdown</Text>
      {slices.length ? (
        <>
          <View style={styles.chart}><Donut size={116} slices={slices} /></View>
          <Legend slices={slices} />
        </>
      ) : <Text style={common.secondary}>Category totals are unavailable.</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: 14 },
  chart: { alignItems: 'center' },
  legend: { flex: 1, gap: 7, minWidth: 0 },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  swatch: { width: 8, height: 8, borderRadius: 3 },
  label: { flex: 1, color: colors.ink, fontSize: 13, lineHeight: 18 },
  percent: { color: colors.ink, fontSize: 14, fontWeight: '700' },
});
