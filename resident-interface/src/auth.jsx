import { createContext, useContext, useEffect, useState } from 'react'
import { AUTH_EXPIRED, stationPost, stationRequest } from './stationApi'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const clearUser = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED, clearUser)
    stationRequest('/auth/me', { signal: controller.signal })
      .then((identity) => { if (!controller.signal.aborted) setUser(identity) })
      .catch(() => { if (!controller.signal.aborted) clearUser() })
      .finally(() => { if (!controller.signal.aborted) setChecking(false) })
    return () => {
      controller.abort()
      window.removeEventListener(AUTH_EXPIRED, clearUser)
    }
  }, [])

  async function logIn(email, password) {
    await stationPost('/auth/login', { email, password })
    setUser(await stationRequest('/auth/me'))
  }

  async function logOut() {
    try {
      await stationRequest('/auth/logout', { method: 'POST' })
    } catch (error) {
      if (error.status !== 401) throw error
    }
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, checking, logIn, logOut }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
