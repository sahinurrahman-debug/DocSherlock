import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toasts } from './components/Toasts'
import { TopBar } from './components/TopBar'
import { WorkspaceProvider } from './context/workspace'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Investigation from './pages/Investigation'

export default function App() {
  return (
    <BrowserRouter>
      <WorkspaceProvider>
        <div className="flex h-full min-h-0 flex-col">
          <TopBar />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/investigate" element={<Investigation />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
        <Toasts />
      </WorkspaceProvider>
    </BrowserRouter>
  )
}
