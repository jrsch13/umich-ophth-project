import { type PropsWithChildren, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { AnalysisStatus } from '../api/types';
import { colors, common } from '../theme';

const statuses = {
  complete: { label: 'Complete', background: colors.greenSoft, color: colors.green },
  pending: { label: 'Pending', background: colors.focus, color: colors.navy },
  processing: { label: 'Processing', background: colors.amberSoft, color: colors.amber },
  failed: { label: 'Analysis needs attention', background: colors.redSoft, color: colors.red },
};

export function StatusBadge({ status }: { status: AnalysisStatus }) {
  const { label, background, color } = statuses[status] ?? statuses.pending;
  return (
    <View style={[styles.badge, { backgroundColor: background }]}>
      <Text style={[styles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

export function Feedback({ message, loading, onRetry }: { message: string; loading?: boolean; onRetry?: () => void }) {
  return (
    <View style={[common.card, styles.feedback]}>
      {loading && <ActivityIndicator color={colors.blue} />}
      <Text accessibilityLiveRegion='polite' style={common.secondary}>{message}</Text>
      {onRetry && <Action label='Try again' onPress={onRetry} />}
    </View>
  );
}

export function Action({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable
      accessibilityRole='button'
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.action, (pressed || disabled) && common.pressed]}
    >
      <Text style={styles.actionText}>{label}</Text>
    </Pressable>
  );
}

export function Disclosure({ title, children }: PropsWithChildren<{ title: string }>) {
  const [open, setOpen] = useState(false);
  return (
    <View style={[common.card, styles.disclosure]}>
      <Pressable accessibilityRole='button' accessibilityState={{ expanded: open }}
        onPress={() => setOpen(!open)} style={styles.disclosureButton}>
        <Text style={styles.disclosureTitle}>{title}</Text>
        <Text importantForAccessibility='no' style={styles.disclosureTitle}>{open ? '−' : '+'}</Text>
      </Pressable>
      {open && <View style={styles.disclosureBody}>{children}</View>}
    </View>
  );
}

export function formatDate(value?: string | null) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

const styles = StyleSheet.create({
  badge: { borderRadius: 8, paddingHorizontal: 9, paddingVertical: 5, alignSelf: 'flex-start' },
  badgeText: { fontSize: 13, fontWeight: '700' },
  feedback: { gap: 12, alignItems: 'flex-start' },
  action: { alignItems: 'center', justifyContent: 'center', paddingHorizontal: 14, paddingVertical: 12, minHeight: 48, borderRadius: 10, backgroundColor: colors.navy },
  actionText: { color: colors.surface, fontSize: 15, fontWeight: '700' },
  disclosure: { paddingVertical: 0 },
  disclosureButton: { minHeight: 48, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  disclosureTitle: { color: colors.blue, fontWeight: '700', fontSize: 15 },
  disclosureBody: { paddingBottom: 16, gap: 10 },
});
