import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useCallback } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { requestMessage } from '../api/client';
import type { SessionListItem } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { Feedback, StatusBadge, formatDate } from '../components/ui';
import type { AppStack } from '../navigation/AppNavigator';
import { colors, common } from '../theme';
import { useRequest } from '../useRequest';

export function SessionsScreen({ navigation }: NativeStackScreenProps<AppStack, 'Sessions'>) {
  const { api, state } = useAuth();
  const load = useCallback((signal: AbortSignal) => api.sessions(signal), [api]);
  const { data, loading, error, reload } = useRequest(load);
  const user = state.phase === 'signedIn' ? state.user : null;

  function renderSession({ item }: { item: SessionListItem }) {
    const title = item.session_label || item.session_id;
    const owner = user?.role === 'admin' ? item.owner_email : null;
    return (
      <Pressable
        accessibilityRole='button'
        accessibilityHint='Opens session analysis'
        onPress={() => navigation.navigate('SessionAnalysis', { session: item })}
        style={({ pressed }) => [common.card, styles.row, pressed && common.pressed]}
      >
        <View style={styles.rowContent}>
          <Text style={styles.label}>{title}</Text>
          <Text style={common.secondary}>{formatDate(item.recorded_at)}</Text>
          {owner && <Text style={common.secondary}>{owner}</Text>}
          <StatusBadge status={item.analysis_status} />
        </View>
        <Text importantForAccessibility='no' style={styles.chevron}>›</Text>
      </Pressable>
    );
  }

  return (
    <SafeAreaView style={common.screen} edges={['bottom']}>
      <FlatList
        testID='sessions-list'
        data={data ?? []}
        keyExtractor={(item) => item.session_id}
        renderItem={renderSession}
        contentContainerStyle={common.page}
        ItemSeparatorComponent={Separator}
        refreshing={loading && data !== null}
        onRefresh={reload}
        ListHeaderComponent={user ? (
          <View style={styles.account}>
            <Text style={styles.accountRole}>{user.role === 'admin' ? 'Administrator' : 'Resident'}</Text>
            <Text style={common.secondary}>{user.email}</Text>
            {error && data?.length ? <Feedback message={requestMessage(error, 'Couldn’t refresh sessions.')} onRetry={reload} /> : null}
          </View>
        ) : undefined}
        ListEmptyComponent={loading ? <Feedback message='Loading sessions…' loading />
          : error ? <Feedback message={requestMessage(error, 'Couldn’t load sessions.')} onRetry={reload} />
            : <Feedback message='No sessions are available yet.' />}
      />
    </SafeAreaView>
  );
}

function Separator() { return <View style={styles.separator} />; }

const styles = StyleSheet.create({
  account: { gap: 3, marginBottom: 16, paddingHorizontal: 2 },
  accountRole: { color: colors.navy, fontSize: 16, fontWeight: '700' },
  row: { minHeight: 86, flexDirection: 'row', alignItems: 'center', gap: 12 },
  rowContent: { flex: 1, gap: 5 },
  label: { color: colors.ink, fontSize: 17, fontWeight: '700' },
  chevron: { fontSize: 28, color: colors.blue },
  separator: { height: 10 },
});
