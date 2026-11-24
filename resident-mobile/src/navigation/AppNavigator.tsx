import { DefaultTheme, NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { SessionListItem } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { Action, Feedback } from '../components/ui';
import { LoginScreen } from '../screens/LoginScreen';
import { SessionsScreen } from '../screens/SessionsScreen';
import { SessionAnalysisScreen } from '../screens/SessionAnalysisScreen';
import { colors, common } from '../theme';

export type AppStack = {
  Login: undefined;
  Sessions: undefined;
  SessionAnalysis: { session: SessionListItem };
};

const Stack = createNativeStackNavigator<AppStack>();
const theme = {
  ...DefaultTheme,
  colors: { ...DefaultTheme.colors, background: colors.background, primary: colors.blue, text: colors.ink, border: colors.softLine },
};

function LogoutButton() {
  const { logOut } = useAuth();
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await logOut();
    } catch {
      Alert.alert('Could not log out', 'Secure storage could not be cleared. Try again.');
      setBusy(false);
    }
  }

  return (
    <Pressable accessibilityRole='button' accessibilityLabel='Log out' onPress={logout} disabled={busy} style={styles.logout}>
      <Text style={styles.logoutLabel}>{busy ? 'Logging out…' : 'Log out'}</Text>
    </Pressable>
  );
}

export function AppNavigator() {
  const { state, restore, logOut } = useAuth();

  if (state.phase === 'restoring' || state.phase === 'restoreError') {
    return (
      <SafeAreaView style={common.screen}>
        <View style={[common.page, styles.restore]}>
          {state.phase === 'restoring'
            ? <Feedback message='Checking your sign-in…' loading />
            : <>
              <Feedback message={state.message} onRetry={() => { void restore(); }} />
              <Action label='Log out' onPress={() => {
                void logOut().catch(() => Alert.alert('Could not log out', 'Secure storage could not be cleared. Try again.'));
              }} />
            </>}
        </View>
      </SafeAreaView>
    );
  }

  return (
    <NavigationContainer theme={theme}>
      <Stack.Navigator screenOptions={{
        headerBackButtonDisplayMode: 'minimal',
        headerTintColor: colors.navy,
        headerTitleStyle: { fontWeight: '700' },
        headerShadowVisible: false,
      }}>
        {state.phase === 'signedIn' ? (
          <Stack.Group screenOptions={{ headerRight: () => <LogoutButton /> }}>
            <Stack.Screen name='Sessions' component={SessionsScreen} />
            <Stack.Screen name='SessionAnalysis' component={SessionAnalysisScreen} options={{ title: 'Session Analysis' }} />
          </Stack.Group>
        ) : <Stack.Screen name='Login' component={LoginScreen} options={{ headerShown: false }} />}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  logout: { minHeight: 44, paddingHorizontal: 5, justifyContent: 'center' },
  logoutLabel: { color: colors.blue, fontWeight: '700', fontSize: 14 },
  restore: { flex: 1, justifyContent: 'center', gap: 12 },
});
