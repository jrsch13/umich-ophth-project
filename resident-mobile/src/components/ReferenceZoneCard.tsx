import { Pressable, StyleSheet, Text, View } from 'react-native';

import { formatPercent } from '../analysis/model';
import type { PostureSummary } from '../api/types';
import { colors, common } from '../theme';
import { Donut, Legend } from './CategoryChart';

export function ReferenceZoneCard({ label, summary, active, onPress }: {
  label: string;
  summary?: PostureSummary;
  active: boolean;
  onPress: () => void;
}) {
  const exposure = summary?.reference_zone_exposure;
  const available = summary?.status === 'available';
  const slices = [
    { label: 'Within reference zone', percent: exposure?.within_percent ?? null, color: colors.green },
    { label: 'Outside reference zone', percent: exposure?.outside_percent ?? null, color: colors.red },
  ];
  const title = summary?.label || label;
  const assessed = `Trial assessed: ${formatPercent(summary?.valid_tracking_percent)}`;

  return (
    <Pressable
      accessibilityRole='button'
      accessibilityState={{ selected: active, disabled: !available }}
      accessibilityLabel={`${title}. ${available ? slices.map((slice) => `${slice.label} ${formatPercent(slice.percent)}`).join('. ') : 'Analysis unavailable'}. ${assessed}`}
      accessibilityHint={available ? 'Updates posture details below' : undefined}
      disabled={!available}
      onPress={onPress}
      style={({ pressed }) => [common.card, styles.card, active && styles.active, pressed && common.pressed]}
    >
      <View style={styles.heading}>
        <Text style={styles.title}>{title}</Text>
        {available && <Text importantForAccessibility='no' style={styles.indicator}>{active ? '●' : '›'}</Text>}
      </View>
      <View style={styles.results}>
        <Donut slices={slices} size={64} />
        {available ? <Legend slices={slices} /> : <Text style={[common.secondary, styles.unavailable]}>
          {summary?.reason === 'view_not_recorded' ? 'View not recorded' : summary?.status === 'insufficient_tracking' ? 'Insufficient tracking' : 'Analysis unavailable'}
        </Text>}
      </View>
      <Text style={[common.secondary, common.number]}>{assessed}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { gap: 8 },
  active: { borderColor: colors.blue, backgroundColor: colors.focus },
  heading: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1, color: colors.ink, fontWeight: '700', fontSize: 17 },
  indicator: { color: colors.blue, fontSize: 17, lineHeight: 20 },
  results: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  unavailable: { flex: 1 },
});
