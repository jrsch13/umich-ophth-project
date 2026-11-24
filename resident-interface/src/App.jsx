import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import AppShell from './components/AppShell'
import { AcceptInvitationPage, LoginPage } from './pages/AuthPages'
import Home from './pages/Home'
import NewSession from './pages/NewSession'
import SessionAnalysis from './pages/SessionAnalysis'
import Cameras from './pages/Cameras'

function ProtectedStation() {
  const { user, checking } = useAuth()
  const location = useLocation()
  if (checking) return <main className='page'><p role='status'>Checking sign-in…</p></main>
  if (!user) {
    return <Navigate to='/login' replace state={{ from: `${location.pathname}${location.search}` }} />
  }
  return <AppShell><Outlet /></AppShell>
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path='/login' element={<LoginPage />} />
        <Route path='/accept-invitation' element={<AcceptInvitationPage />} />
        <Route element={<ProtectedStation />}>
          <Route path='/' element={<Home />} />
          <Route path='/new' element={<NewSession />} />
          <Route path='/history' element={<SessionAnalysis />} />
          <Route path='/history/:sessionId' element={<SessionAnalysis />} />
          <Route path='/cameras' element={<Cameras />} />
        </Route>
        <Route path='*' element={<Navigate to='/' replace />} />
      </Routes>
    </AuthProvider>
  )
}
