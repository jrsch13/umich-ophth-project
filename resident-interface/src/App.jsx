import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Home from './pages/Home'
import NewSession from './pages/NewSession'
import History from './pages/History'
import Cameras from './pages/Cameras'
export default function App(){return <AppShell><Routes><Route path='/' element={<Home/>}/><Route path='/new' element={<NewSession/>}/><Route path='/history' element={<History/>}/><Route path='/cameras' element={<Cameras/>}/><Route path='*' element={<Navigate to='/' replace/>}/></Routes></AppShell>}
