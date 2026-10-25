import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, manualCertificatePdf } from '../services/api'
import type { CertificateTemplate } from '../types/certificate'

export function AdminCertificatesPage() {
  const [name, setName] = useState('John Doe')
  const [college, setCollege] = useState('Example Engineering College')
  const [team, setTeam] = useState('Team Nova')
  const [active, setActive] = useState<CertificateTemplate | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.templates().then(items => setActive(items.find(item => item.is_active) || null)).catch(() => setActive(null)) }, [])
  async function generate(download: boolean) {
    setError('')
    try { await manualCertificatePdf(name.trim(), college.trim(), team.trim(), download) }
    catch (err) { setError(err instanceof Error ? err.message : 'Certificate generation failed') }
  }
  return <>
    <div className="admin-page-heading"><div><span className="eyebrow">/ STEP 4</span><h1>GENERATE CERTIFICATE<span>.</span></h1><p>Enter participant details to test the active template and download a PDF.</p></div><Link className="button button-outline" to="/admin/certificates/templates">EDIT TEMPLATE →</Link></div>
    {error && <div className="form-error" role="alert">{error}</div>}
    <section className="admin-info-card email-form"><h2>TEST CERTIFICATE</h2><label>Participant name<input value={name} onChange={event => setName(event.target.value)} /></label><label>College name (optional)<input value={college} onChange={event => setCollege(event.target.value)} /></label><label>Team name (optional)<input value={team} onChange={event => setTeam(event.target.value)} /></label>{active && <p>Active template prints: <strong>Name{active.include_college ? ' · College' : ''}{active.include_team ? ' · Team' : ''}</strong>. Change this in the <Link className="text-action" to="/admin/certificates/templates">template editor</Link>.</p>}<div className="certificate-actions"><button disabled={!name.trim()} onClick={() => void generate(false)}>PREVIEW CERTIFICATE</button><button disabled={!name.trim()} onClick={() => void generate(true)}>GENERATE PDF</button></div><p>The PDF is generated immediately from the active template. No participant record is required. Empty fields are left off the certificate.</p></section>
  </>
}
