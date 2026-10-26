import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import { useAuth } from '../hooks/useAuth'
import type { CsvParticipant, CsvParticipantPage, CsvPreview, CsvPreviewRow } from '../types/participant'

type ParticipantField = 'name' | 'email' | 'team_name' | 'college'
// A draft without an id is a new participant; with an id it edits an existing one.
type ParticipantDraft = Pick<CsvParticipant, ParticipantField> & { id?: number }
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const STATUS_LABELS: Record<CsvPreviewRow['status'], string> = { VALID: 'NEW', REVIEW: 'NEEDS REVIEW', DUPLICATE: 'EXACT DUPLICATE', INVALID: 'INVALID' }

export function AdminParticipantsPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManage = user?.role !== 'STAFF'
  const [page, setPage] = useState(1)
  // searchInput updates on every keystroke; search follows after a pause and drives the request.
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('name:asc')
  const [data, setData] = useState<CsvParticipantPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [editing, setEditing] = useState<ParticipantDraft | null>(null)
  const [editError, setEditError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<ParticipantField, string>>>({})
  const [saving, setSaving] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [sharedWarning, setSharedWarning] = useState('')

  useEffect(() => {
    if (searchInput === search) return
    const timer = setTimeout(() => { setSearch(searchInput); setPage(1) }, 250)
    return () => clearTimeout(timer)
  }, [searchInput, search])

  useEffect(() => {
    let active = true
    const [sortBy, sortDir] = sort.split(':')
    setLoading(true); setListError('')
    api.csvParticipants(search, sortBy, sortDir, page).then(result => {
      if (!active) return
      if (result.source !== 'csv') throw new Error('This server is still using Google Sheets. Deploy the updated CSV backend; a Sheets connection is not required.')
      setData(result)
    }).catch(err => {
      if (!active) return
      setData(null)
      setListError(err instanceof Error && err.message.includes('Google Sheets')
        ? 'This server is still using Google Sheets. Deploy the updated CSV backend; a Sheets connection is not required.'
        : err instanceof Error ? err.message : 'Could not load participants.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [search, sort, page, reload])

  async function upload() {
    if (!file) return
    setBusy(true); setError(''); setMessage('')
    try { setPreview(await api.previewCsv(file)) }
    catch (err) { setError(err instanceof Error ? err.message : 'CSV preview failed') }
    finally { setBusy(false) }
  }
  // Reviewable duplicates are imported only from the review modal; exact duplicates never are.
  async function importCsv(includeReviewed = false) {
    if (!file || !preview || busy) return
    setBusy(true); setError('')
    try {
      const approved = includeReviewed ? preview.rows.filter(row => row.status === 'REVIEW').map(row => row.line) : []
      const result = await api.importCsv(file, preview.digest, approved)
      setMessage(`${result.imported_new} new imported · ${result.imported_reviewed} reviewed duplicates imported · ${result.review_skipped} reviewable duplicates skipped · ${result.duplicates} exact duplicates skipped · ${result.invalid} invalid rows skipped.`)
      setPreview(null); setFile(null); setReviewing(false); setReload(value => value + 1)
    } catch (err) { setError(err instanceof Error ? err.message : 'CSV import failed') }
    finally { setBusy(false) }
  }
  async function remove(id: number, name: string) {
    if (!window.confirm(`Delete ${name} from participants?`)) return
    try { await api.deleteCsvParticipant(id); setSelected(previous => { const next = new Set(previous); next.delete(id); return next }); setReload(value => value + 1) }
    catch (err) { setError(err instanceof Error ? err.message : 'Delete failed') }
  }
  async function saveEdit(event?: React.FormEvent<HTMLFormElement>, allowSharedEmail = false) {
    event?.preventDefault()
    if (!editing || saving) return
    const clean = (value: string | null) => (value ?? '').trim().replace(/\s+/g, ' ')
    const person = { name: clean(editing.name), email: editing.email.trim().toLowerCase(),
      team_name: clean(editing.team_name) || null, college: clean(editing.college) || null,
      ...(allowSharedEmail ? { allow_shared_email: true } : {}) }
    const problems: Partial<Record<ParticipantField, string>> = {}
    if (!person.name) problems.name = 'Name is required.'
    if (!person.email) problems.email = 'Email is required.'
    else if (!EMAIL_PATTERN.test(person.email)) problems.email = 'Enter a valid email address, e.g. name@example.com.'
    setFieldErrors(problems); setEditError(''); setSharedWarning('')
    if (Object.keys(problems).length) return
    setSaving(true)
    try {
      if (editing.id === undefined) {
        const created = await api.createCsvParticipant(person)
        setEditing(null); setMessage(`${created.name} added.`); setSearchInput(created.email); setSearch(created.email); setPage(1); setReload(value => value + 1)
      } else {
        const updated = await api.updateCsvParticipant(editing.id, person)
        setData(previous => previous ? { ...previous, items: previous.items.map(item => item.id === updated.id ? updated : item) } : previous)
        setEditing(null); setMessage(`${updated.name} updated.`); setReload(value => value + 1)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 428) setSharedWarning(err.message) // email belongs to someone else: confirm first
      else if (err instanceof ApiError && err.status === 409) setFieldErrors({ email: err.message })
      else if (err instanceof ApiError && err.status === 422) setEditError('The server rejected these details. Check that the email address is valid and no field is longer than 160 characters.')
      else setEditError(err instanceof Error ? err.message : 'Could not save participant.')
    }
    finally { setSaving(false) }
  }
  async function clear() {
    if (!window.confirm('Clear ALL imported participants? Send history will remain.')) return
    try { await api.clearCsvParticipants(); setSelected(new Set()); setMessage('Participants cleared.'); setReload(value => value + 1) }
    catch (err) { setError(err instanceof Error ? err.message : 'Clear failed') }
  }
  function sample() {
    const blob = new Blob(['name,email,team_name,college\r\nAarav Kumar,aarav@example.com,Team Nova,ABC College\r\nMeera Shah,meera@example.com,,\r\n'], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'tech-roulette-sample.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function toggle(id: number) { setSelected(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next }) }
  const pageIds = data?.items.map(person => person.id) ?? []
  const legacyServer = listError.includes('still using Google Sheets')
  return <>
    <div className="admin-page-heading"><div><span className="eyebrow">/ STEP 1</span><h1>PARTICIPANTS<span>.</span></h1><p>Upload a CSV, check every row, then import the valid participants.</p></div></div>
    {error && <div className="form-error" role="alert">{error}</div>}{message && <div className="form-success" role="status">{message}</div>}
    {canManage && <section className="admin-info-card csv-upload"><h2>UPLOAD PARTICIPANTS CSV</h2><p>Required columns: <code>name,email</code>. Optional columns: <code>team_name,college</code> (blank cells are allowed). Common header variations are accepted.</p><div className="csv-file-row"><label className="button button-outline" htmlFor="participants-csv">CHOOSE FILE<input id="participants-csv" className="visually-hidden" type="file" accept=".csv,text/csv" onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null) }} /></label><span>{file?.name || 'No file chosen'}</span><button className="button button-dark" type="button" disabled={!file || busy || legacyServer} onClick={() => void upload()}>{busy ? 'CHECKING…' : 'PREVIEW CSV'}</button></div><button className="text-action" type="button" onClick={sample}>DOWNLOAD SAMPLE CSV ↓</button></section>}
    {preview && <section className="admin-info-card"><h2>IMPORT PREVIEW</h2><div className="csv-counts"><strong>{preview.valid} new</strong><strong>{preview.review} need review</strong><strong>{preview.duplicates} exact duplicates</strong><strong>{preview.invalid} invalid</strong></div><div className="participant-table-wrap"><table className="participants-table csv-table"><thead><tr><th>LINE</th><th>NAME</th><th>EMAIL</th><th>TEAM</th><th>COLLEGE</th><th>STATUS / REASON</th></tr></thead><tbody>{preview.rows.map(row => <tr key={row.line}><td>{row.line}</td><td>{row.name || '—'}</td><td>{row.email || '—'}</td><td>{row.team_name || '—'}</td><td>{row.college || '—'}</td><td><strong>{STATUS_LABELS[row.status]}</strong>{row.reason && <small>{row.reason}</small>}</td></tr>)}</tbody></table></div><div className="certificate-actions"><button type="button" disabled={busy} onClick={() => setPreview(null)}>CANCEL</button><button type="button" disabled={busy || !(preview.review + preview.duplicates)} onClick={() => setReviewing(true)}>REVIEW DUPLICATES</button><button type="button" disabled={busy || !preview.valid} onClick={() => void importCsv()}>{busy ? 'IMPORTING…' : `IMPORT ${preview.valid} NEW PARTICIPANTS`}</button></div>{preview.review > 0 && <p>Rows that share an email with someone else are not imported unless you approve them in REVIEW DUPLICATES.</p>}</section>}
    {reviewing && preview && <div className="edit-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setReviewing(false) }}><section className="admin-info-card edit-participant duplicate-review" role="dialog" aria-modal="true" aria-label="Review duplicates"><h2>REVIEW DUPLICATES</h2><p>{preview.review} reviewable (same email, different name) · {preview.duplicates} exact (same name and email — never imported).</p>
      {preview.rows.filter(row => row.status === 'REVIEW' || row.status === 'DUPLICATE').map(row => <div key={row.line} className="duplicate-item"><div className={`duplicate-head${row.status === 'DUPLICATE' ? ' exact' : ''}`}><strong>LINE {row.line} · {row.status === 'REVIEW' ? 'REVIEWABLE DUPLICATE' : 'EXACT DUPLICATE — WILL NOT BE IMPORTED'}</strong><small>{row.reason}</small></div><div className="participant-table-wrap"><table className="participants-table duplicate-compare"><thead><tr><th>RECORD</th><th>NAME</th><th>EMAIL</th><th>TEAM</th><th>COLLEGE</th></tr></thead><tbody><tr className="incoming"><td>INCOMING · LINE {row.line}</td><td>{row.name}</td><td>{row.email}</td><td>{row.team_name || '—'}</td><td>{row.college || '—'}</td></tr>{row.matches.map(match => <tr key={`${match.source}-${match.id ?? match.line}`}><td>{match.source === 'existing' ? `EXISTING #${match.id}` : `CSV LINE ${match.line}`}</td><td>{match.name}</td><td>{match.email}</td><td>{match.team_name || '—'}</td><td>{match.college || '—'}</td></tr>)}</tbody></table></div></div>)}
      <div className="certificate-actions"><button type="button" disabled={busy} onClick={() => setReviewing(false)}>CLOSE</button><button type="button" disabled={busy || !preview.review} onClick={() => void importCsv(true)}>{busy ? 'IMPORTING…' : `IMPORT ELIGIBLE DUPLICATES (${preview.valid} NEW + ${preview.review} REVIEWED)`}</button></div><p>Closing imports nothing.</p></section></div>}
    <section className="participant-panel csv-list">
      <div className="participant-panel-heading"><span>IMPORTED PARTICIPANTS</span><span className="panel-heading-actions"><span>{loading ? 'LOADING…' : listError ? 'UNAVAILABLE' : `${data?.total ?? 0} RESULTS`}</span>{canManage && <button type="button" className="add-participant" disabled={legacyServer} onClick={() => { setEditing({ name: '', email: '', team_name: '', college: '' }); setEditError(''); setFieldErrors({}); setSharedWarning('') }}>+ ADD PARTICIPANT</button>}</span></div>
      {listError ? <div className="participant-empty" role="alert"><strong>COULD NOT LOAD CSV PARTICIPANTS</strong><p>{listError}</p><button className="button button-outline" type="button" onClick={() => setReload(value => value + 1)}>TRY AGAIN →</button></div>
        : !data ? <div className="participant-empty">Loading participants…</div>
        : !loading && data.total === 0 && !search ? <div className="participant-empty"><strong>NO PARTICIPANTS IMPORTED</strong><p>Choose a CSV above to start. The required columns are name and email; team name and college are optional.</p></div>
        : <>
          <div className="csv-toolbar"><input type="search" aria-label="Search participants" placeholder="Search name, email, team, college…" value={searchInput} onChange={event => setSearchInput(event.target.value)} /><select aria-label="Sort participants" value={sort} onChange={event => { setSort(event.target.value); setPage(1) }}><option value="name:asc">Name A–Z</option><option value="name:desc">Name Z–A</option><option value="created_at:desc">Newest first</option><option value="college:asc">College A–Z</option><option value="team_name:asc">Team A–Z</option></select><span>{selected.size} selected</span><button type="button" onClick={() => setSelected(previous => new Set([...previous, ...pageIds]))}>SELECT ALL ON PAGE</button><button type="button" onClick={() => setSelected(new Set())}>DESELECT ALL</button></div>
          <div className="participant-table-wrap"><table className="participants-table csv-table"><thead><tr><th><input type="checkbox" aria-label="Select all on page" checked={pageIds.length > 0 && pageIds.every(id => selected.has(id))} onChange={() => setSelected(previous => { const next = new Set(previous); if (pageIds.every(id => next.has(id))) pageIds.forEach(id => next.delete(id)); else pageIds.forEach(id => next.add(id)); return next })} /></th><th>NAME</th><th>EMAIL</th><th>TEAM NAME</th><th>COLLEGE</th>{canManage && <th>ACTION</th>}</tr></thead><tbody>{data?.items.map(person => <tr key={person.id}><td><input type="checkbox" aria-label={`Select ${person.name}`} checked={selected.has(person.id)} onChange={() => toggle(person.id)} /></td><td>{person.name}</td><td>{person.email}</td><td>{person.team_name || '—'}</td><td>{person.college || '—'}</td>{canManage && <td><button type="button" className="text-action" onClick={() => { setEditing({ ...person }); setEditError(''); setFieldErrors({}); setSharedWarning('') }}>EDIT</button> <button type="button" className="text-action" onClick={() => void remove(person.id, person.name)}>DELETE</button></td>}</tr>)}</tbody></table></div>
          {data?.items.length === 0 && <div className="participant-empty">No matching participants.</div>}
        </>}
    </section>
    {(data?.total_pages ?? 0) > 1 && <div className="participant-pagination"><span>PAGE {page} OF {data?.total_pages}</span><div><button disabled={page === 1} onClick={() => setPage(value => value - 1)}>PREVIOUS</button><button disabled={page === data?.total_pages} onClick={() => setPage(value => value + 1)}>NEXT</button></div></div>}
    {canManage && selected.size > 0 && <button type="button" className="button button-dark" onClick={() => navigate('/admin/email/compose', { state: { participantIds: [...selected] } })}>COMPOSE FOR {selected.size} SELECTED →</button>}
    {canManage && !!data?.total && <button type="button" className="text-action csv-clear" onClick={() => void clear()}>CLEAR PARTICIPANTS</button>}
    {editing && <div className="edit-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !saving) setEditing(null) }}><form className="admin-info-card edit-participant" aria-label={editing.id === undefined ? 'Add participant' : 'Edit participant'} noValidate onSubmit={event => void saveEdit(event)}><h2>{editing.id === undefined ? 'ADD PARTICIPANT' : 'EDIT PARTICIPANT'}</h2>{editError && <div className="form-error" role="alert">{editError}</div>}{([['name', 'Name', true], ['email', 'Email', true], ['team_name', 'Team Name', false], ['college', 'College Name', false]] as const).map(([field, label, required]) => <label key={field}>{label}{required ? ' *' : ' (optional)'}<input required={required} maxLength={field === 'email' ? 320 : 160} type={field === 'email' ? 'email' : 'text'} value={editing[field] ?? ''} aria-invalid={!!fieldErrors[field]} aria-describedby={fieldErrors[field] ? `${field}-error` : undefined} onChange={event => { const value = event.target.value; setEditing(previous => previous ? { ...previous, [field]: value } : previous); setFieldErrors(previous => ({ ...previous, [field]: undefined })); setSharedWarning('') }} />{fieldErrors[field] && <small id={`${field}-error`} className="field-error" role="alert">{fieldErrors[field]}</small>}</label>)}{sharedWarning && <div className="form-error" role="alert">{sharedWarning}<div className="certificate-actions"><button type="button" disabled={saving} onClick={() => void saveEdit(undefined, true)}>{editing.id === undefined ? 'ADD ANYWAY' : 'SAVE ANYWAY'}</button></div></div>}<div className="certificate-actions"><button type="button" disabled={saving} onClick={() => setEditing(null)}>CANCEL</button><button type="submit" disabled={saving}>{saving ? 'SAVING…' : editing.id === undefined ? 'ADD PARTICIPANT' : 'SAVE'}</button></div></form></div>}
  </>
}
