import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'

function DemoShellPlaceholder() {
  return <div data-testid="demo-shell">demo shell</div>
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/demo/*" element={<DemoShellPlaceholder />} />
    </Routes>
  )
}
