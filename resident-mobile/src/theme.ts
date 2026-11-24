import { StyleSheet } from 'react-native';

export const colors = {
  background: '#F3F6F7',
  surface: '#FFFFFF',
  ink: '#102A43',
  navy: '#102D45',
  blue: '#255E83',
  muted: '#495D6B',
  line: '#CAD5DC',
  softLine: '#E4EBEF',
  gold: '#F1BD61',
  green: '#237451',
  greenSoft: '#E7F4EC',
  red: '#A8303A',
  redSoft: '#FBEAEC',
  amber: '#8A4A16',
  amberSoft: '#F8EEDF',
  focus: '#E9F2F8',
};

export const common = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  page: { width: '100%', maxWidth: 640, alignSelf: 'center', paddingHorizontal: 18, paddingTop: 18, paddingBottom: 32 },
  section: { marginBottom: 22, gap: 12 },
  card: { backgroundColor: colors.surface, borderColor: colors.softLine, borderWidth: 1, borderRadius: 16, padding: 16 },
  sectionTitle: { color: colors.ink, fontSize: 21, fontWeight: '700' },
  body: { color: colors.ink, fontSize: 15, lineHeight: 22 },
  secondary: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  pressed: { opacity: 0.74 },
  number: { fontVariant: ['tabular-nums'] },
});
