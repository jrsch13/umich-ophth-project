import { line } from 'd3-shape';
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Line, Path, Rect, Text as ChartText } from 'react-native-svg';

import { categoryBands, categoryColor, formatTime, nearestPointIndex } from '../analysis/model';
import type { PostureSummary, TimePoint } from '../api/types';
import { colors, common } from '../theme';

const height = 216;
const margin = { left: 40, right: 15, top: 12, bottom: 35 };
const channels = {
  right_value: { label: 'Right shoulder', color: '#255E83' },
  left_value: { label: 'Left shoulder', color: '#9A4717' },
  value: { label: 'Measurement', color: '#255E83' },
};

export function PostureTimeSeries({ points, summary, selectedIndex, onSelect }: {
  points: TimePoint[];
  summary: PostureSummary;
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const [width, setWidth] = useState(0);
  const shoulder = summary.metric === 'shoulder_hiking';
  const data = useMemo(() => {
    const keys = shoulder ? ['right_value', 'left_value'] as const : ['value'] as const;
    const values = points.flatMap((point) => keys.map((key) => point[key])).filter(
      (value): value is number => typeof value === 'number' && Number.isFinite(value),
    );
    const minimum = values.length ? Math.min(...values) : 0;
    const maximum = values.length ? Math.max(...values) : 1;
    const padding = Math.max((maximum - minimum) * 0.08, 0.5);
    return { keys, minimum: minimum - padding, maximum: maximum + padding, bands: categoryBands(points) };
  }, [points, shoulder]);

  const plotWidth = Math.max(1, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;
  const start = points[0]?.time_seconds ?? 0;
  const end = points[points.length - 1]?.time_seconds ?? start;
  const duration = end > start ? end - start : 1;
  const x = (time: number) => margin.left + (time - start) / duration * plotWidth;
  const y = (value: number) => margin.top + (data.maximum - value) / (data.maximum - data.minimum) * plotHeight;
  const selectAt = (offset: number) => {
    const fraction = Math.max(0, Math.min(1, (offset - margin.left) / plotWidth));
    const index = nearestPointIndex(points, start + fraction * duration);
    if (index >= 0) onSelect(index);
  };
  const selected = points[selectedIndex];
  const xTicks = end > start ? [start, start + duration / 2, end] : [start];
  const yTicks = [data.minimum, (data.minimum + data.maximum) / 2, data.maximum];

  return (
    <View style={[common.card, styles.card]}>
      <Text accessibilityRole='header' style={common.sectionTitle}>Posture over time</Text>
      <Text style={common.secondary}>{summary.unit === 'degrees' ? 'Measurement (°)' : summary.unit}</Text>
      <View style={styles.plot} onLayout={(event) => setWidth(event.nativeEvent.layout.width)} testID='time-series-layout'>
        {width > margin.left + margin.right && (
          <>
            <Svg width={width} height={height} pointerEvents='none' accessible={false} importantForAccessibility='no-hide-descendants'>
              {data.bands.map((band) => {
                const category = summary.category_distribution.find((entry) => entry.key === band.key);
                return category && <Rect key={`${band.start}-${band.key}`} x={x(band.start)} y={margin.top}
                  width={x(band.end) - x(band.start)} height={plotHeight} fill={categoryColor(summary.metric, category)} opacity={0.16} />;
              })}
              {yTicks.map((value) => (
                <GridLine key={value} value={value} start={margin.left} width={plotWidth} y={y(value)} />
              ))}
              {xTicks.map((time, index) => (
                <ChartText key={time} x={x(time)} y={height - margin.bottom + 15} fontSize={11} fill={colors.muted}
                  textAnchor={index === 0 ? 'start' : index === xTicks.length - 1 ? 'end' : 'middle'}>
                  {formatTime(time, duration < 4 ? 1 : 0)}
                </ChartText>
              ))}
              <ChartText x={margin.left + plotWidth / 2} y={height - 3} fontSize={11} fill={colors.muted} textAnchor='middle'>Session time</ChartText>
              {data.keys.map((key) => {
                const path = line<TimePoint>()
                  .defined((point) => typeof point[key] === 'number' && Number.isFinite(point[key]))
                  .x((point) => x(point.time_seconds)).y((point) => y(point[key] ?? 0))(points);
                return <Path key={key} d={path ?? undefined} fill='none' stroke={channels[key].color} strokeWidth={2.3} />;
              })}
              {selected && <Line x1={x(selected.time_seconds)} x2={x(selected.time_seconds)} y1={margin.top} y2={margin.top + plotHeight} stroke={colors.navy} strokeDasharray='3 4' />}
              {(selected || points.length === 1) && data.keys.map((key) => {
                const point = selected ?? points[0];
                const value = point[key];
                return typeof value === 'number'
                  ? <Circle key={key} cx={x(point.time_seconds)} cy={y(value)} r={4.5} fill={channels[key].color} stroke={colors.surface} strokeWidth={1.5} />
                  : null;
              })}
            </Svg>
            <Pressable
              testID='time-series-touch'
              style={StyleSheet.absoluteFill}
              accessibilityRole='adjustable'
              accessibilityLabel='Posture time series'
              accessibilityHint='Tap the chart to select the nearest recorded point. Swipe up or down to move between points with a screen reader.'
              accessibilityValue={{ text: selected ? formatTime(selected.time_seconds) : 'No point selected' }}
              accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
              onAccessibilityAction={(event) => {
                const offset = event.nativeEvent.actionName === 'increment' ? 1 : -1;
                onSelect(Math.max(0, Math.min(points.length - 1, selectedIndex + offset)));
              }}
              onPress={(event) => selectAt(event.nativeEvent.locationX)}
            />
          </>
        )}
      </View>
      {shoulder && <View style={styles.seriesLegend}>
        {(['right_value', 'left_value'] as const).map((key) => (
          <View key={key} style={styles.key}>
            <View style={[styles.lineKey, { backgroundColor: channels[key].color }]} />
            <Text style={common.secondary}>{channels[key].label}</Text>
          </View>
        ))}
      </View>}
      {selected && <Text style={[common.body, common.number]}>Selected at {formatTime(selected.time_seconds)}</Text>}
      <Text style={common.secondary}>Shading follows the category colors below. Tap the chart to inspect a point.</Text>
    </View>
  );
}

function GridLine({ value, start, width, y }: { value: number; start: number; width: number; y: number }) {
  return (
    <>
      <Line x1={start} x2={start + width} y1={y} y2={y} stroke={colors.line} strokeDasharray='3 3' />
      <ChartText x={start - 5} y={y + 4} fontSize={11} fill={colors.muted} textAnchor='end'>{Number(value.toFixed(1))}</ChartText>
    </>
  );
}

const styles = StyleSheet.create({
  card: { gap: 8 },
  plot: { height },
  seriesLegend: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  key: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  lineKey: { width: 14, height: 3, borderRadius: 2 },
});
