import { useSearchParams } from 'react-router-dom'
import { AdminCertificateTemplatesPage } from './AdminCertificateTemplatesPage'
import { EmailTemplatesPage } from './EmailTemplatesPage'

export function TemplatesPage() {
  const [params, setParams] = useSearchParams()
  const certificate = params.get('tab') === 'certificates'
  return <><div className="admin-page-heading"><div><span className="eyebrow">/ CONTENT LIBRARY</span><h1>TEMPLATES<span>.</span></h1><p>Manage email messages and certificate layouts.</p></div></div>
    <div className="template-tabs" role="tablist" aria-label="Template types"><button id="email-tab" role="tab" aria-controls="template-panel" aria-selected={!certificate} onClick={() => setParams({ tab: 'email' })}>EMAIL TEMPLATES</button><button id="certificate-tab" role="tab" aria-controls="template-panel" aria-selected={certificate} onClick={() => setParams({ tab: 'certificates' })}>CERTIFICATE TEMPLATES</button></div>
    <div id="template-panel" role="tabpanel" aria-labelledby={certificate ? 'certificate-tab' : 'email-tab'}>{certificate ? <AdminCertificateTemplatesPage embedded /> : <EmailTemplatesPage embedded />}</div>
  </>
}
