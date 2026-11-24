import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Linking, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { orderedPoints, postures } from '../analysis/model';
import { ApiError, requestMessage } from '../api/client';
import type { MetricKey, PostureSummary } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { CategoryChart } from '../components/CategoryChart';
import { PostureTimeSeries } from '../components/PostureTimeSeries';
import { ReferenceZoneCard } from '../components/ReferenceZoneCard';
import { SelectedPointCard } from '../components/SelectedPointCard';
import { Disclosure, Feedback, StatusBadge, formatDate } from '../components/ui';
import type { AppStack } from '../navigation/AppNavigator';
import { colors, common } from '../theme';
import { useRequest } from '../useRequest';

export function SessionAnalysisScreen({ route }: NativeStackScreenProps<AppStack, 'SessionAnalysis'>) {
  const { api, state } = useAuth();
  const session = route.params.session;
  const id = session.session_id;
  const load = useCallback((signal: AbortSignal) => api.session(id, signal), [api, id]);
  const { data, loading, error, reload } = useRequest(load);
  const [selection, setSelection] = useState<MetricKey>('neck_flexion_extension');
  const status = data?.analysis_status.status ?? session.analysis_status;
  const stage = data?.analysis_status.stage;
  const active = data?.posture_summaries.find((summary) => summary.metric === selection && summary.status === 'available')
    ?? data?.posture_summaries.find((summary) => summary.status === 'available');
  const owner = state.phase === 'signedIn' && state.user.role === 'admin' ? session.owner_email : undefined;
  const processing = status === 'pending' || status === 'processing';

  useEffect(() => {
    if (!processing || !data) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const latest = await api.status(id, controller.signal);
        if (!controller.signal.aborted && (latest.status !== status || latest.stage !== stage)) await reload();
      } catch {
        // A temporary connection error should leave the last available analysis visible.
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 5000);
    }

    timer = setTimeout(poll, 5000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, data, id, processing, reload, stage, status]);

  return (
    <SafeAreaView style={common.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={common.page} refreshControl={<RefreshControl refreshing={loading && !!data} onRefresh={reload} />}>
        <View style={common.section}>
          <View style={[common.card, styles.session]}>
            <Text accessibilityRole='header' style={styles.sessionTitle}>{data?.metadata.session_label || session.session_label || id}</Text>
            <Text style={common.secondary}>{formatDate(data?.metadata.started_at || data?.metadata.ended_at || data?.metadata.created_at || session.recorded_at)}</Text>
            {owner && <Text style={common.secondary}>{owner}</Text>}
            <StatusBadge status={status} />
          </View>
          {loading && !data && <Feedback message='Loading session analysis…' loading />}
          {error ? <Feedback message={requestMessage(error, error instanceof ApiError && error.status === 404
            ? 'This session is unavailable.' : 'Couldn’t load session analysis.')} onRetry={reload} /> : null}
          {data && processing && <Feedback message='Analysis is still in progress. Results appear here as they become available.' />}
          {data && status === 'failed' && <Feedback message='Analysis did not finish. Any available results are shown below.' />}
        </View>

        {data && (
          <>
            <View style={common.section}>
              <Text accessibilityRole='header' style={common.sectionTitle}>Reference Zone Exposure</Text>
              <Text style={common.secondary}>Trial assessed is the share of the trial with enough body landmarks to assess the posture.</Text>
              {postures.map(({ key, name }) => (
                <ReferenceZoneCard key={key} label={name} summary={data.posture_summaries.find((entry) => entry.metric === key)}
                  active={active?.metric === key} onPress={() => setSelection(key)} />
              ))}
            </View>
            {active && <PostureDetails key={`${id}:${active.metric}`} id={id} summary={active} reviewMediaAvailable={data.review_media_available} />}
            <Methodology />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function PostureDetails({ id, summary, reviewMediaAvailable }: { id: string; summary: PostureSummary; reviewMediaAvailable: boolean }) {
  const { api } = useAuth();
  const [selectedFrame, setSelectedFrame] = useState<number | null>(null);
  const metric = summary.metric;
  const load = useCallback((signal: AbortSignal) => api.series(id, metric, signal), [api, id, metric]);
  const { data, loading, error, reload } = useRequest(load);
  const points = useMemo(() => orderedPoints(data?.points ?? []), [data]);
  const index = points.findIndex((point) => point.frame === selectedFrame);

  return (
    <View style={common.section}>
      <Text accessibilityRole='header' style={common.sectionTitle}>{summary.label} details</Text>
      {loading ? <Feedback message='Loading measurements…' loading />
        : error ? <Feedback message={requestMessage(error, 'Couldn’t load measurements.')} onRetry={reload} />
          : points.length ? <PostureTimeSeries points={points} summary={summary} selectedIndex={index}
            onSelect={(point) => setSelectedFrame(points[point].frame)} />
            : <Feedback message='No measured points are available for this posture.' />}
      <CategoryChart summary={summary} />
      <Disclosure title='About this measurement'>
        <Text style={common.body}>{summary.reference_zone_exposure.rule_explanation}</Text>
        {metric === 'shoulder_hiking' && <Text style={common.secondary}>
          The raised-shoulder adjustment adds +1 to the upper-arm posture score. The right, left, and bilateral labels describe the prototype’s detected posture states.
        </Text>}
      </Disclosure>
      <SelectedPointCard sessionId={id} summary={summary} point={points[index]} reviewMediaAvailable={reviewMediaAvailable} />
    </View>
  );
}

function Methodology() {
  const [linkFailed, setLinkFailed] = useState(false);
  return (
    <Disclosure title='About RULA'>
      <Text style={common.body}>This prototype reports selected posture components of the Rapid Upper Limb Assessment.</Text>
      <Text accessibilityRole='link' style={styles.citation} onPress={() => {
        void Linking.openURL('https://doi.org/10.1016/0003-6870(93)90080-S').catch(() => setLinkFailed(true));
      }}>
        McAtamney &amp; Corlett. RULA: a survey method for the investigation of work-related upper limb disorders. Applied Ergonomics, 1993.
      </Text>
      {linkFailed && <Text style={common.secondary}>Couldn’t open the citation link.</Text>}
    </Disclosure>
  );
}

const styles = StyleSheet.create({
  session: { gap: 8 },
  sessionTitle: { color: colors.ink, fontSize: 25, fontWeight: '800', letterSpacing: -0.4 },
  citation: { color: colors.blue, fontSize: 14, lineHeight: 21, textDecorationLine: 'underline' },
});
