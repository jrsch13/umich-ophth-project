import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Home from './pages/Home'
import NewSession from './pages/NewSession'
import SessionAnalysis from './pages/SessionAnalysis'
import Cameras from './pages/Cameras'
export default function App(){return <AppShell><Routes><Route path='/' element={<Home/>}/><Route path='/new' element={<NewSession/>}/><Route path='/history' element={<SessionAnalysis/>}/><Route path='/history/:sessionId' element={<SessionAnalysis/>}/><Route path='/cameras' element={<Cameras/>}/><Route path='*' element={<Navigate to='/' replace/>}/></Routes></AppShell>}
