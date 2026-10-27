import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function AdminLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  async function handleLogout() { await logout(); navigate('/admin/login', { replace: true }) }
  return <div className="admin-shell"><aside className="admin-sidebar"><a className="admin-logo" href="/">✳ <span>TECHROULETTE</span></a><div className="admin-sidebar-label">CONTROL ROOM</div><nav aria-label="Admin navigation">
    <NavLink to="/admin/dashboard">▣ <span>Overview</span></NavLink>
    <NavLink to="/admin/participants">☷ <span>Participants</span></NavLink>
    {user?.role !== 'STAFF' && <>
      <NavLink to="/admin/csv">☷ <span>CSV Management</span></NavLink>
      <NavLink to="/admin/templates">▧ <span>Templates</span></NavLink>
      <NavLink to="/admin/certificates">▤ <span>Generate certificate</span></NavLink>
      <NavLink to="/admin/email/compose">✉ <span>Compose email</span></NavLink>
      <NavLink to="/admin/email/campaigns">◷ <span>Send history</span></NavLink>
    </>}
    <NavLink to="/admin/users">♟ <span>User management</span></NavLink>
  </nav><div className="admin-sidebar-bottom"><a href="/">← View website</a><button type="button" onClick={handleLogout}>↗ Sign out</button></div></aside><div className="admin-main"><header className="admin-topbar"><span>TECHROULETTE / ADMIN</span><div><span className="admin-role">{user?.role.replace('_', ' ')}</span><span className="admin-avatar">{user?.name.charAt(0).toUpperCase()}</span></div></header><main className="admin-content"><Outlet /></main></div></div>
}
