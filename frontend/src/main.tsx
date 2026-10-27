import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AuthProvider } from './hooks/useAuth'
import { AdminLayout } from './layouts/AdminLayout'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { AdminParticipantsPage } from './pages/AdminParticipantsPage'
import { EmailCampaignsPage } from './pages/EmailCampaignsPage'
import { AdminLoginPage } from './pages/AdminLoginPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AdminCertificatesPage } from './pages/AdminCertificatesPage'
import { TemplatesPage } from './pages/TemplatesPage'
import { CsvManagementPage } from './pages/CsvManagementPage'
import { EmailComposePage } from './pages/EmailComposePage'
import { HomePage } from './pages/HomePage'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><AuthProvider><Routes>
  <Route path="/" element={<HomePage />} />
  <Route path="/admin/login" element={<AdminLoginPage />} />
  <Route element={<ProtectedRoute />}><Route element={<AdminLayout />}>
    <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
    <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
    <Route path="/admin/participants" element={<AdminParticipantsPage />} />
    <Route element={<ProtectedRoute certificateAdminOnly />}>
      <Route path="/admin/certificates" element={<AdminCertificatesPage />} />
      <Route path="/admin/csv" element={<CsvManagementPage />} />
      <Route path="/admin/templates" element={<TemplatesPage />} />
      <Route path="/admin/certificates/templates" element={<Navigate to="/admin/templates?tab=certificates" replace />} />
      <Route path="/admin/email/templates" element={<Navigate to="/admin/templates?tab=email" replace />} />
      <Route path="/admin/email/compose" element={<EmailComposePage />} />
      <Route path="/admin/email/campaigns" element={<EmailCampaignsPage />} />
    </Route>
    <Route path="/admin/users" element={<AdminUsersPage />} />
  </Route></Route>
  <Route path="*" element={<Navigate to="/" replace />} />
</Routes></AuthProvider></BrowserRouter></React.StrictMode>)
