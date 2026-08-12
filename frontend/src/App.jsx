import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import DemoShell from './pages/DemoShell'
import SiteHeader from './components/SiteHeader'
import SiteFooter from './components/SiteFooter'

export default function App() {
  return (
    <>
      <SiteHeader />
      <main>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/demo/*" element={<DemoShell />} />
        </Routes>
      </main>
      <SiteFooter />
    </>
  )
}
