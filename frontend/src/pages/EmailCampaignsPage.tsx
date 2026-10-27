import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, finishCampaign } from '../services/api'
import type { Campaign } from '../types/email'

export function EmailCampaignsPage() {
  const [searchParams] = useSearchParams()
  const sentId = Number(searchParams.get('sent'))
  const interrupted = searchParams.has('interrupted')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [detail, setDetail] = useState<Campaign | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const load = async () => { const rows = await api.campaigns(); setCampaigns(rows); if (detail) setDetail(await api.campaign(detail.id)) }
  useEffect(() => { void api.campaigns().then(setCampaigns).catch(e => setError(e.message)) }, [])
  useEffect(() => { if (sentId > 0) void api.campaign(sentId).then(setDetail).catch(e => setError(e.message)) }, [sentId])
  async function action(fn: () => Promise<unknown>, success: string) {
    try { await fn(); setMessage(success); setError(''); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'Action failed') }
  }
  async function retryFailed(id: number) {
    const result = await api.retryCampaign(id)
    await finishCampaign(id, result.status)
  }
  async function continueSending(id: number) {
    const result = await api.continueCampaign(id)
    await finishCampaign(id, result.status)
  }
  return <><div className="admin-page-heading"><div><span className="eyebrow">/ EMAIL</span><h1>SEND HISTORY<span>.</span></h1><p>Review each manual send, inspect failures, and retry failed recipients.</p></div><Link className="button button-dark" to="/admin/email/compose">NEW EMAIL →</Link></div>
    {error && <div className="form-error" role="alert">{error}</div>}{message && <div className="form-success">{message}</div>}
    {interrupted && detail?.status === 'PROCESSING' && <div className="admin-notice"><span>ⓘ</span><p>The send was interrupted. Review the campaign and continue any pending recipients.</p></div>}
    <div className="participant-panel"><div className="participant-table-wrap"><table className="participants-table email-table"><thead><tr><th>SEND</th><th>RECIPIENTS</th><th>STATUS</th><th>SENT</th><th>FAILED</th><th>SKIPPED</th><th>DATE</th><th>DETAILS</th></tr></thead><tbody>{campaigns.map(row => <tr key={row.id}><td>{row.name}</td><td>{row.recipient_count}</td><td>{row.status}</td><td>{row.sent_count}</td><td>{row.failed_count}</td><td>{row.skipped_count}</td><td>{new Date(row.started_at || row.created_at).toLocaleString()}</td><td><button className="text-action" onClick={() => void api.campaign(row.id).then(setDetail).catch(e => setError(e.message))}>VIEW</button></td></tr>)}</tbody></table></div>{campaigns.length === 0 && <div className="empty-state">No sends yet.</div>}</div>
    {detail && <section className="admin-info-card"><div className="email-detail-heading"><h2>{detail.name}</h2><button onClick={() => setDetail(null)}>CLOSE</button></div><p>{detail.status} · {detail.sent_count} sent · {detail.failed_count} failed · {detail.recipient_count} recipients</p><p>Certificate: {detail.attach_certificate ? detail.certificate_template_name || `Template #${detail.certificate_template_id}` : 'None'} · Configuration saved when this campaign was created.</p><div className="certificate-actions">{detail.status === 'PROCESSING' && <button onClick={() => void action(() => continueSending(detail.id), 'Pending deliveries processed.')}>CONTINUE SEND</button>}{detail.deliveries?.some(d => d.status === 'FAILED' && d.attempt_count < 3) && <button onClick={() => { if (window.confirm(`Retry only the ${detail.failed_count} failed deliveries?`)) void action(() => retryFailed(detail.id), 'Failed deliveries retried.') }}>RETRY FAILED</button>}</div><div className="participant-table-wrap"><table className="participants-table email-table"><thead><tr><th>PARTICIPANT</th><th>EMAIL</th><th>STATUS</th><th>ATTEMPTS</th><th>SENT AT</th><th>FAILURE</th></tr></thead><tbody>{detail.deliveries?.map(d => <tr key={d.id}><td>{d.participant_name}</td><td>{d.email}</td><td>{d.status}</td><td>{d.attempt_count}</td><td>{d.sent_at ? new Date(d.sent_at).toLocaleString() : '—'}</td><td>{d.failure_reason || '—'}</td></tr>)}</tbody></table></div></section>}
  </>
}
