import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fetchExportPdf } from '../../services/api'
import { generateCertificateZip, selectExportIds } from '../../services/certificateExport'
import type { CertificateTemplate } from '../../types/certificate'
import type { ExportFailure, ExportProgress } from '../../types/certificateExport'
import type { DatasetSummary } from '../../types/dataset'
import type { CsvParticipant } from '../../types/participant'

const PAGE_SIZE = 50
export function BulkCertificateDownload({ templates }: { templates: CertificateTemplate[] }) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetId, setDatasetId] = useState<number | undefined>()
  const [people, setPeople] = useState<CsvParticipant[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [reload, setReload] = useState(0)
  const [templateId, setTemplateId] = useState<number | undefined>()
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [all, setAll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<'idle' | 'starting' | 'generating' | 'packaging' | 'ready' | 'error'>('idle')
  const [progress, setProgress] = useState<ExportProgress | null>(null)
  const [failures, setFailures] = useState<ExportFailure[]>([])
  const [failurePage, setFailurePage] = useState(1)
  const [error, setError] = useState('')
  const [download, setDownload] = useState<{ url: string; filename: string; template: string; count: number } | null>(null)
  const guard = useRef(false), mounted = useRef(true)
  const controller = useRef<AbortController | null>(null)
  const downloadUrl = useRef('')
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; controller.current?.abort(); if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current) }
  }, [])
  useEffect(() => {
    api.datasets().then(setDatasets).catch(e => setLoadError(e.message))
  }, [reload])
  useEffect(() => {
    let active = true
    setLoading(true); setLoadError(''); setPeople([])
    api.allCsvParticipants(datasetId).then(items => { if (active) setPeople(items) })
      .catch(e => { if (active) setLoadError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [datasetId, reload])
  useEffect(() => {
    setTemplateId(previous => previous ?? templates.find(t => t.is_active)?.id ?? templates[0]?.id)
  }, [templates])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (guard.current) e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  const filtered = useMemo(() => people.filter(p => `${p.name} ${p.email} ${p.college ?? ''} ${p.team_name ?? ''}`.toLowerCase().includes(deferredSearch.toLowerCase())), [people, deferredSearch])
  const ids = selectExportIds(people, selected, all)
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)))
  const shown = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const template = templates.find(t => t.id === templateId)
  const scope = datasetId ? `dataset “${datasets.find(d => d.id === datasetId)?.name ?? datasetId}”` : 'all datasets (all participants)'

  function toggle(id: number) {
    const next = new Set(all ? people.map(p => p.id) : selected)
    if (next.has(id)) next.delete(id); else next.add(id)
    setAll(false); setSelected(next)
  }
  async function start() {
    if (guard.current || !templateId || !ids.length) return
    guard.current = true; setBusy(true); setError(''); setFailures([]); setFailurePage(1); setPhase('starting'); setProgress(null)
    if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current)
    downloadUrl.current = ''; setDownload(null)
    const abort = new AbortController(); controller.current = abort
    let exportId: string | undefined
    try {
      const run = await api.createCertificateExport({ request_id: crypto.randomUUID(), template_id: templateId,
        selection: all ? 'all' : 'selected', dataset_id: datasetId, participant_ids: all ? [] : ids, expected_count: ids.length })
      exportId = run.id
      if (abort.signal.aborted) return
      const result = await generateCertificateZip(run, recipient => fetchExportPdf(run.id, recipient.id, abort.signal), value => {
        if (mounted.current) { setProgress(value); setPhase(value.phase) }
      })
      if (!mounted.current) return
      setFailures(result.failures)
      if (!result.blob) { setPhase('error'); setError('No certificates were generated. No empty ZIP was downloaded. See the participant failures below.'); return }
      const filename = `tech-roulette-certificates${result.failures.length ? '-partial' : ''}.zip`
      const url = URL.createObjectURL(result.blob); downloadUrl.current = url
      setDownload({ url, filename, count: result.generated, template: run.template_name }); setPhase('ready')
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename
      document.body.append(anchor); anchor.click(); anchor.remove()
    } catch (e) {
      if (mounted.current) { setPhase('error'); setError(e instanceof Error ? e.message : 'Certificate generation failed.') }
    } finally {
      if (exportId) void api.deleteCertificateExport(exportId).catch(() => { /* An interrupted cleanup remains private and expires automatically. */ })
      guard.current = false
      if (mounted.current) setBusy(false)
    }
  }

  const percent = progress ? Math.floor(progress.attempted / progress.total * 100) : 0
  return <section className="admin-info-card bulk-certificates">
    <h2>DOWNLOAD PARTICIPANT CERTIFICATES</h2><p>Generate personalized PDFs in a single ZIP. This action sends no emails and does not update send history.</p>
    <fieldset className="csv-workspace email-form" disabled={busy}>
      <label>Participant scope<select value={datasetId ?? ''} onChange={e => { setDatasetId(e.target.value ? Number(e.target.value) : undefined); setSelected(new Set()); setAll(false); setPage(1); setSearch('') }}><option value="">All datasets — all participants</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name} · {d.participant_count} participants{d.archived ? ' (archived)' : ''}</option>)}</select></label>
      <label>Certificate template<select value={templateId ?? ''} onChange={e => setTemplateId(Number(e.target.value))}><option value="" disabled>Choose a certificate…</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name}{t.is_active ? ' (active)' : ''}</option>)}</select></label>
      {!templates.length && <p><Link to="/admin/templates?tab=certificates">Add a certificate template →</Link></p>}
      {loading ? <p role="status">Loading participants…</p> : loadError ? <div className="form-error" role="alert">{loadError}<button type="button" onClick={() => setReload(v => v + 1)}>RETRY</button></div> : <>
        <div className="csv-toolbar"><input type="search" aria-label="Search certificate participants" placeholder="Search participants…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} /><button type="button" onClick={() => { setAll(true); setSelected(new Set()) }}>SELECT ALL {people.length} {datasetId ? 'IN THIS DATASET' : 'ACROSS DATASETS'}</button><button type="button" onClick={() => { setAll(false); setSelected(new Set()) }}>DESELECT ALL</button></div>
        <p>Select All includes the entire chosen scope, including other pages and rows hidden by search.</p>
        <div className="participant-table-wrap"><table className="participants-table csv-table"><thead><tr><th>SELECT</th><th>PARTICIPANT / ID</th><th>EMAIL</th><th>COLLEGE / TEAM</th></tr></thead><tbody>{shown.map(p => <tr key={p.id}><td><input type="checkbox" aria-label={`Select ${p.name}, participant ${p.id}`} checked={all || selected.has(p.id)} onChange={() => toggle(p.id)} /></td><td>{p.name}<small>#{p.id}</small></td><td>{p.email}</td><td>{p.college || '—'}<small>{p.team_name || '—'}</small></td></tr>)}</tbody></table></div>
        {!filtered.length && <p>No participants match this scope/search.</p>}
        <div className="csv-toolbar"><button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>PREVIOUS</button><span>Page {currentPage} / {Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))} · {filtered.length} matching participants</span><button type="button" disabled={currentPage * PAGE_SIZE >= filtered.length} onClick={() => setPage(currentPage + 1)}>NEXT</button></div>
      </>}
      <div className="bulk-certificate-review"><strong>{ids.length} PARTICIPANTS SELECTED</strong><p>Scope: {scope}<br />Certificate: {template?.name ?? 'None selected'}</p></div>
      <p>Up to 5,000 participants per run, 3 MB per PDF and 100 MB per ZIP. Keep this page open until the ZIP is ready.</p>
      <button className="button button-dark" type="button" disabled={loading || !!loadError || !ids.length || ids.length > 5000 || !templateId} onClick={() => void start()}>GENERATE & DOWNLOAD ZIP →</button>
    </fieldset>
    {phase !== 'idle' && <div className="bulk-certificate-status" aria-live="polite" aria-busy={busy}>
      <strong>{phase === 'starting' ? 'PREPARING SELECTION…' : phase === 'generating' ? 'GENERATING CERTIFICATES…' : phase === 'packaging' ? 'PREPARING ZIP…' : phase === 'ready' ? failures.length ? 'PARTIAL ZIP READY' : 'ZIP READY' : 'GENERATION FAILED'}</strong>
      {progress && <><progress aria-label="Certificate generation progress" max={progress.total} value={progress.attempted} /><p>{progress.attempted} / {progress.total} processed ({percent}%) · {progress.generated} PDFs generated · {progress.failed} failed during generation</p></>}
      {download && <><p>{download.count} certificates · {download.template}. Your download was requested. If it did not start, use the button below.</p><a className="button button-dark" href={download.url} download={download.filename}>DOWNLOAD {failures.length ? 'PARTIAL ' : ''}ZIP ↓</a></>}
    </div>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {failures.length > 0 && <details className="bulk-certificate-failures" open><summary>{failures.length} participants missing from the ZIP · {failures.filter(f => !f.attempted).length} not attempted</summary><div className="participant-table-wrap"><table className="participants-table csv-table"><thead><tr><th>PARTICIPANT</th><th>REASON</th></tr></thead><tbody>{failures.slice((failurePage - 1) * PAGE_SIZE, failurePage * PAGE_SIZE).map(f => <tr key={f.id}><td>{f.name}<small>#{f.id}</small></td><td>{f.reason}</td></tr>)}</tbody></table></div>{failures.length > PAGE_SIZE && <div className="csv-toolbar"><button disabled={failurePage === 1} onClick={() => setFailurePage(failurePage - 1)}>PREVIOUS FAILURES</button><span>{failurePage} / {Math.ceil(failures.length / PAGE_SIZE)}</span><button disabled={failurePage * PAGE_SIZE >= failures.length} onClick={() => setFailurePage(failurePage + 1)}>NEXT FAILURES</button></div>}</details>}
  </section>
}
