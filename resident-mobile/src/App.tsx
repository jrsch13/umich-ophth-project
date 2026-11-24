import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'react-native';

import { AuthProvider } from './auth/AuthProvider';
import { AppNavigator } from './navigation/AppNavigator';

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar barStyle='dark-content' />
      <AuthProvider><AppNavigator /></AuthProvider>
    </SafeAreaProvider>
  );
}
