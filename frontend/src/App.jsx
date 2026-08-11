import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import DemoShell from './pages/DemoShell'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/demo/*" element={<DemoShell />} />
    </Routes>
  )
}
