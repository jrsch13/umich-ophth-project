import { useCallback, useState } from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';

import { formatTime, formatValue } from '../analysis/model';
import { requestMessage } from '../api/client';
import type { PostureSummary, TimePoint, View as CameraView } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { colors, common } from '../theme';
import { useRequest } from '../useRequest';
import { Feedback } from './ui';

type Detail = { label: string; value: string };

function pointDetails(summary: PostureSummary, point: TimePoint): Detail[] {
  const details = [{ label: 'Time', value: formatTime(point.time_seconds) }];
  const measurement = (label: string, value: number | null | undefined) => ({ label, value: formatValue(value, summary.unit) });
  const category = summary.category_distribution.find((item) => item.key === point.category);

  switch (summary.metric) {
    case 'neck_flexion_extension':
      details.push(measurement('Neck angle', point.value));
      break;
    case 'forward_trunk_lean':
      details.push(measurement('Forward trunk angle', point.posture_angle_deg), measurement('Change from neutral', point.value));
      break;
    case 'lateral_trunk_lean':
      details.push(measurement('Lateral lean angle', point.posture_angle_deg), measurement('Change from neutral', point.value));
      break;
    case 'shoulder_hiking':
      details.push(measurement('Right shoulder', point.right_value), measurement('Left shoulder', point.left_value));
      break;
  }
  if (category) {
    const label = summary.metric === 'lateral_trunk_lean' ? 'RULA side-bending adjustment'
      : summary.metric === 'shoulder_hiking' ? 'Classification' : 'Category';
    details.push({ label, value: category.label });
    if (category.rula_score !== null) details.push({ label: 'RULA posture score', value: String(category.rula_score) });
    if (summary.metric === 'shoulder_hiking' && typeof category.rula_adjustment_present === 'boolean') {
      details.push({ label: 'RULA raised-shoulder adjustment', value: category.rula_adjustment_present ? 'Present' : 'Absent' });
    }
  }
  return details;
}

export function SelectedPointCard({ sessionId, summary, point, reviewMediaAvailable }: {
  sessionId: string;
  summary: PostureSummary;
  point?: TimePoint;
  reviewMediaAvailable: boolean;
}) {
  return (
    <View style={[common.card, styles.card]}>
      <Text accessibilityRole='header' style={common.sectionTitle}>Selected point</Text>
      {point ? (
        <>
          <View accessibilityLiveRegion='polite' style={styles.details}>
            {pointDetails(summary, point).map(({ label, value }) => (
              <View key={label} style={styles.detailRow}>
                <Text style={[common.secondary, styles.detailLabel]}>{label}</Text>
                <Text style={[common.body, common.number, styles.detailValue]}>{value}</Text>
              </View>
            ))}
          </View>
          {reviewMediaAvailable === true ? (
            <RecordedFrame key={point.frame} sessionId={sessionId} view={summary.view} point={point} />
          ) : <Text style={common.secondary}>Recorded frame unavailable on mobile for this session.</Text>}
        </>
      ) : <Text style={common.secondary}>Select a point on the chart to see its measurement and category.</Text>}
    </View>
  );
}

function RecordedFrame({ sessionId, view, point }: { sessionId: string; view: CameraView; point: TimePoint }) {
  const { api } = useAuth();
  const frame = point.frame;
  const load = useCallback((signal: AbortSignal) => api.frame(sessionId, view, frame, signal), [api, frame, sessionId, view]);
  const { loading, data, error } = useRequest(load);
  const [decodeFailed, setDecodeFailed] = useState(false);
  if (loading) return <Feedback message='Loading recorded frame…' loading />;
  if (error || !data || decodeFailed) return <Text style={common.secondary}>{requestMessage(error, 'Recorded frame unavailable.')}</Text>;
  return <Image source={{ uri: data }} resizeMode='contain' style={styles.frame}
    accessible accessibilityLabel={`Recorded ${view} frame at ${formatTime(point.time_seconds)}`} onError={() => setDecodeFailed(true)} />;
}

const styles = StyleSheet.create({
  card: { gap: 12 },
  details: { gap: 8 },
  detailRow: { flexDirection: 'row', alignItems: 'baseline', gap: 12 },
  detailLabel: { flex: 1, flexBasis: '44%' },
  detailValue: { flex: 1, flexBasis: '48%', fontWeight: '600' },
  frame: { width: '100%', aspectRatio: 4 / 3, borderRadius: 10, backgroundColor: colors.background },
});
