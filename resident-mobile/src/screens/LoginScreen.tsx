import { type ComponentRef, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError, requestMessage } from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import { Action } from '../components/ui';
import { colors, common } from '../theme';

function loginMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 401) return 'That email or password is incorrect. Try again.';
  if (error instanceof ApiError && error.status === 429) return 'Too many attempts. Wait a moment and try again.';
  return requestMessage(error, 'Couldn’t log in. Try again.');
}

export function LoginScreen() {
  const { state, configured, logIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordInput = useRef<ComponentRef<typeof TextInput>>(null);
  const canSubmit = configured && Boolean(email.trim() && password) && !busy;
  const notice = error || (state.phase === 'signedOut' ? state.notice : undefined);

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await logIn(email.trim(), password);
    } catch (failure) {
      setError(loginMessage(failure));
    } finally {
      setPassword('');
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={common.screen}>
      <KeyboardAvoidingView style={common.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps='handled'>
          <View style={styles.content}>
            <View style={styles.banner}>
              <View style={styles.accent} />
              <Text accessibilityRole='header' style={styles.title}>Ergonomic Training Station</Text>
              <Text style={styles.bannerText}>Sign in to review your posture analysis.</Text>
            </View>
            <View style={[common.card, styles.form]}>
              <View style={styles.field}>
                <Text style={styles.label}>Email</Text>
                <TextInput
                  accessibilityLabel='Email'
                  autoCapitalize='none'
                  autoComplete='username'
                  autoCorrect={false}
                  editable={!busy}
                  keyboardType='email-address'
                  onChangeText={setEmail}
                  onSubmitEditing={() => passwordInput.current?.focus()}
                  placeholder='name@example.edu'
                  placeholderTextColor={colors.muted}
                  returnKeyType='next'
                  style={styles.input}
                  value={email}
                />
              </View>
              <View style={styles.field}>
                <Text style={styles.label}>Password</Text>
                <TextInput
                  ref={passwordInput}
                  accessibilityLabel='Password'
                  autoCapitalize='none'
                  autoComplete='current-password'
                  editable={!busy}
                  onChangeText={setPassword}
                  onSubmitEditing={submit}
                  returnKeyType='go'
                  secureTextEntry
                  style={styles.input}
                  value={password}
                />
              </View>
              {!configured && <Text accessibilityRole='alert' style={styles.notice}>
                Set the station’s HTTPS API address in .env.local, then reload the app.
              </Text>}
              {notice && <Text accessibilityRole='alert' accessibilityLiveRegion='polite' style={styles.notice}>{notice}</Text>}
              <Action label={busy ? 'Logging in…' : 'Log In'} onPress={submit} disabled={!canSubmit} />
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 18, paddingVertical: 24 },
  content: { width: '100%', maxWidth: 440, alignSelf: 'center', gap: 14 },
  banner: { borderRadius: 19, backgroundColor: colors.navy, padding: 23, gap: 12 },
  accent: { backgroundColor: colors.gold, width: 31, height: 4, borderRadius: 2 },
  title: { color: colors.surface, fontWeight: '800', fontSize: 32, lineHeight: 37, letterSpacing: -0.6 },
  bannerText: { color: '#DCE9F0', fontSize: 15, lineHeight: 22 },
  form: { gap: 16, padding: 18 },
  field: { gap: 6 },
  label: { color: colors.ink, fontSize: 15, fontWeight: '700' },
  input: { minHeight: 49, borderWidth: 1, borderColor: colors.line, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, color: colors.ink, fontSize: 16, backgroundColor: colors.background },
  notice: { color: colors.red, fontSize: 14, lineHeight: 20 },
});
