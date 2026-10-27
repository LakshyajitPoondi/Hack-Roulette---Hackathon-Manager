import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, downloadDataset } from '../services/api'
import { deduplicateExact, inspectRows, nameColumn, replaceValues, sortRows } from '../services/csvEditor'
import type { CsvIssue, Dataset, DatasetPreview, DatasetRow, DatasetSummary } from '../types/dataset'

type Operation = { label: string; rows: DatasetRow[]; affected: number[] }
const PAGE_SIZE = 50
const issueKey = (i: CsvIssue) => JSON.stringify([i.row_id, i.column, i.problem, i.value])

function EditableCsvCell({ initial, label, onSave, onCancel }: { initial: string; label: string; onSave: (value: string) => void; onCancel: () => void }) {
  // Typing stays inside this cell; the table and validation rerender only after Save.
  const [value, setValue] = useState(initial)
  return <form className="csv-cell-form" onSubmit={e => { e.preventDefault(); onSave(value) }}>
    <input autoFocus aria-label={label} value={value} maxLength={10000} onKeyDown={e => { if (e.key === 'Escape') onCancel() }} onChange={e => setValue(e.target.value)} />
    <button>SAVE</button><button type="button" onClick={onCancel}>CANCEL</button>
  </form>
}

export function CsvManagementPage() {
  const navigate = useNavigate()
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [rows, setRows] = useState<DatasetRow[]>([])
  const [undo, setUndo] = useState<DatasetRow[][]>([])
  const [dirty, setDirty] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [uploadName, setUploadName] = useState('')
  const [rename, setRename] = useState('')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [issuePage, setIssuePage] = useState(1)
  const [groupPage, setGroupPage] = useState(1)
  const [column, setColumn] = useState(0)
  const [find, setFind] = useState('')
  const [replacement, setReplacement] = useState('')
  const [ignoreCase, setIgnoreCase] = useState(false)
  const [descending, setDescending] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editing, setEditing] = useState<{ id: number; column: number; value: string } | null>(null)
  const [operation, setOperation] = useState<Operation | null>(null)
  const [rejected, setRejected] = useState<Set<string>>(new Set())
  const [preview, setPreview] = useState<DatasetPreview | null>(null)
  const [previewPage, setPreviewPage] = useState(1)
  const [approved, setApproved] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const refreshList = () => api.datasets().then(setDatasets)
  useEffect(() => { refreshList().catch(e => setError(e.message)) }, [])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : 'Operation failed') }
    finally { setBusy(false) }
  }
  function load(item: Dataset) {
    setDataset(item); setRows(item.rows); setRename(item.name); setUndo([]); setDirty(false); setPreview(null)
    setApproved([]); setSelected(new Set()); setRejected(new Set()); setEditing(null); setOperation(null)
    setPage(1); setIssuePage(1); setGroupPage(1); setSearch(''); setFilter('all'); setColumn(0)
  }
  async function open(id: number) {
    if (dirty && !window.confirm('Discard unsaved edits and open this dataset?')) return
    await run(async () => load(await api.dataset(id)))
  }
  function change(next: DatasetRow[]) {
    setUndo(previous => [...previous.slice(-9), rows]); setRows(next); setDirty(true); setPreview(null); setApproved([])
    setSelected(new Set()); setEditing(null); setOperation(null); setPage(1); setIssuePage(1); setGroupPage(1)
  }
  async function saveDraft() {
    if (!dataset) throw new Error('Select a dataset')
    const saved = dirty ? await api.saveDataset(dataset.id, dataset.revision, rows) : dataset
    setDataset(saved); setDirty(false)
    return saved
  }
  const inspection = useMemo(() => {
    if (!dataset) return { issues: [], duplicateGroups: [] }
    // Local feedback is immediate; saved drafts display the authoritative server's full email checks.
    return dirty ? inspectRows(dataset.headers, rows) : { issues: dataset.issues, duplicateGroups: dataset.duplicate_groups }
  }, [dataset?.headers, dataset?.issues, dataset?.duplicate_groups, rows, dirty])
  const byId = useMemo(() => new Map(rows.map(r => [r.id, r])), [rows])
  const issuesByRow = useMemo(() => {
    const result = new Map<number, CsvIssue[]>()
    inspection.issues.forEach(i => result.set(i.row_id, [...(result.get(i.row_id) ?? []), i]))
    return result
  }, [inspection])
  const duplicates = useMemo(() => new Set(inspection.duplicateGroups.flatMap(g => g.row_ids)), [inspection])
  const visible = useMemo(() => rows.filter(r => r.cells.some(c => c.toLowerCase().includes(deferredSearch.toLowerCase())) &&
    (filter === 'all' || (filter === 'errors' && issuesByRow.get(r.id)?.some(i => i.severity === 'error')) ||
     (filter === 'warnings' && issuesByRow.get(r.id)?.some(i => i.severity === 'warning')) || (filter === 'duplicates' && duplicates.has(r.id)))),
    [rows, deferredSearch, filter, issuesByRow, duplicates])
  const currentPage = Math.min(page, Math.max(1, Math.ceil(visible.length / PAGE_SIZE)))
  const pageRows = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const displayedIssues = inspection.issues.filter(i => !rejected.has(issueKey(i)))
  const currentIssuePage = Math.min(issuePage, Math.max(1, Math.ceil(displayedIssues.length / PAGE_SIZE)))
  const title = (id: number) => `${byId.get(id)?.cells[dataset ? nameColumn(dataset.headers) : 0] || 'Unnamed'} (row ${id + 1})`
  function editCell(id: number, col: number) {
    setFilter('all'); setSearch(''); setPage(Math.floor(rows.findIndex(r => r.id === id) / PAGE_SIZE) + 1)
    setEditing({ id, column: col, value: byId.get(id)?.cells[col] ?? '' })
  }
  function removeRows(ids: Set<number>, label: string) {
    setOperation({ label, rows: rows.filter(r => !ids.has(r.id)), affected: rows.filter(r => ids.has(r.id)).map(r => r.id) })
  }
  async function reviewImport(nextApproved: number[] = []) {
    const saved = await saveDraft()
    setPreview(await api.previewDataset(saved.id, nextApproved)); setApproved(nextApproved)
    await refreshList()
  }
  return <>
    <div className="admin-page-heading"><div><span className="eyebrow">/ DATA WORKSPACE</span><h1>CSV MANAGEMENT<span>.</span></h1><p>Prepare a dataset, review changes, then add eligible participants. Original uploads are preserved.</p></div><Link className="button button-outline" to="/admin/participants">PARTICIPANTS →</Link></div>
    {error && <div className="form-error" role="alert">{error}</div>}{message && <div className="form-success" role="status">{message}</div>}
    {busy && <p role="status">Saving or loading dataset…</p>}
    <fieldset className="csv-workspace" disabled={busy}>
      <section className="admin-info-card"><h2>UPLOAD A NEW DATASET</h2><p>UTF-8 CSV · up to 5 MB, 5,000 rows and 100 columns · name and email required; team and college optional. Other columns stay in the dataset.</p>
        <form className="csv-toolbar" onSubmit={e => { e.preventDefault(); if (file && (!dirty || window.confirm('Discard unsaved edits and upload another dataset?'))) void run(async () => { load(await api.uploadDataset(uploadName, file)); setFile(null); setUploadName(''); await refreshList(); setMessage('Dataset saved. Review and edit it below before importing.') }) }}>
          <label>Dataset name<input required maxLength={160} value={uploadName} onChange={e => setUploadName(e.target.value)} /></label>
          <label>CSV file<input type="file" accept=".csv,text/csv" onChange={e => { const next = e.target.files?.[0] ?? null; setFile(next); if (next && !uploadName) setUploadName(next.name.replace(/\.csv$/i, '').slice(0, 160)) }} /></label>
          <button disabled={!file || !uploadName.trim()} className="button button-dark">UPLOAD & SAVE →</button>
        </form>
      </section>
      <section className="admin-info-card"><h2>SAVED DATASETS</h2><label>Open dataset<select value={dataset?.id ?? ''} onChange={e => { if (e.target.value) void open(Number(e.target.value)) }}><option value="">Select a dataset…</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name} · {d.participant_count} participants · {new Date(d.created_at).toLocaleDateString()}{d.archived ? ' · archived' : ''}</option>)}</select></label>
        {datasets.length === 0 && <p>No datasets yet. Upload a CSV to begin.</p>}
        {dataset && <><p>{dataset.participant_count} linked participants · Created {new Date(dataset.created_at).toLocaleString()} · {dataset.original_filename}{dataset.is_legacy && ' · Recovered from existing participant records'}</p>
          <div className="csv-toolbar"><label>Dataset name<input maxLength={160} value={rename} onChange={e => setRename(e.target.value)} /></label><button disabled={!rename.trim()} onClick={() => void run(async () => { const saved = await api.renameDataset(dataset.id, rename); setDataset({ ...dataset, name: saved.name }); await refreshList(); setMessage('Dataset renamed.') })}>RENAME</button>
            <button onClick={() => void run(async () => { const saved = await api.archiveDataset(dataset.id, !dataset.archived); setDataset({ ...dataset, archived: saved.archived }); setPreview(null); await refreshList() })}>{dataset.archived ? 'RESTORE' : 'ARCHIVE'}</button>
            <button onClick={() => void run(async () => { await downloadDataset(dataset.id, true); setMessage('Original bytes downloaded as text for safe inspection. The original upload is unchanged.') })}>DOWNLOAD ORIGINAL</button>
            <button disabled={dirty} onClick={() => void run(async () => { await downloadDataset(dataset.id) })}>EXPORT SAVED CSV</button>
            <button disabled={dirty || dataset.archived || !dataset.participant_count} onClick={() => navigate('/admin/email/compose', { state: { datasetId: dataset.id } })}>REUSE IN COMPOSE →</button>
          </div><p>Exports escape spreadsheet formulas. Original downloads contain the exact uploaded bytes. Existing participant details are retained when a dataset reuses their name and email.</p></>}
      </section>
      {dataset && <fieldset className="csv-workspace" disabled={dataset.archived}>
        {dataset.archived && <p role="status">Restore this archived dataset to edit or import it. Its records and history are preserved.</p>}
        <section className="admin-info-card"><h2>EDIT DATASET {dirty && '· UNSAVED CHANGES'}</h2>
          <div className="csv-counts"><strong>{rows.length} ROWS</strong><strong>{new Set(inspection.issues.filter(i => i.severity === 'error').map(i => i.row_id)).size} WITH ERRORS</strong><strong>{duplicates.size} FLAGGED FOR REVIEW</strong></div>
          <div className="csv-toolbar"><label>Column<select value={column} onChange={e => setColumn(Number(e.target.value))}>{dataset.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}</select></label><label>Find (whole cell)<input value={find} onChange={e => setFind(e.target.value)} /></label><label>Replace with<input value={replacement} onChange={e => setReplacement(e.target.value)} /></label><label className="email-check"><input type="checkbox" checked={ignoreCase} onChange={e => setIgnoreCase(e.target.checked)} /> Ignore case</label><button onClick={() => { const result = replaceValues(rows, column, find, replacement, ignoreCase); setOperation({ label: `Replace exact values in ${dataset.headers[column]}`, rows: result.rows, affected: result.affected.map(r => r.id) }) }}>PREVIEW REPLACEMENTS</button></div>
          <div className="csv-toolbar"><label>Sort direction<select value={descending ? 'desc' : 'asc'} onChange={e => setDescending(e.target.value === 'desc')}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label><button onClick={() => change(sortRows(rows, column, descending))}>SORT BY {dataset.headers[column]}</button><button onClick={() => { const next = rows.map(r => ({ ...r, cells: r.cells.map(c => c.trim()) })); setOperation({ label: 'Trim surrounding whitespace only', rows: next, affected: rows.filter((r, i) => r.cells.some((c, j) => c !== next[i].cells[j])).map(r => r.id) }) }}>PREVIEW TRIM WHITESPACE</button>
            <button disabled={!undo.length} onClick={() => { const previous = undo.at(-1)!; setRows(previous); setUndo(undo.slice(0, -1)); setDirty(true); setPreview(null); setApproved([]); setEditing(null); setOperation(null); setSelected(new Set()) }}>UNDO LATEST</button>
            <button className="button button-dark" disabled={!!editing} onClick={() => void run(async () => { await saveDraft(); await refreshList(); setMessage('Draft saved and validated. Participant records have not been changed.') })}>SAVE DRAFT</button>
          </div>
          <div className="csv-toolbar"><input type="search" aria-label="Search CSV cells" placeholder="Search all columns…" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} /><select aria-label="Filter CSV rows" value={filter} onChange={e => { setFilter(e.target.value); setPage(1) }}><option value="all">All rows</option><option value="errors">Rows with errors</option><option value="warnings">Rows with warnings</option><option value="duplicates">Potential duplicates</option></select><button disabled={!selected.size} onClick={() => removeRows(selected, 'Remove selected rows from this draft')}>PREVIEW REMOVE {selected.size} SELECTED</button></div>
          <div className="participant-table-wrap csv-editor-scroll"><table className="participants-table csv-table csv-editor"><thead><tr><th><input type="checkbox" aria-label="Select displayed rows" checked={pageRows.length > 0 && pageRows.every(r => selected.has(r.id))} onChange={e => setSelected(previous => { const next = new Set(previous); pageRows.forEach(r => e.target.checked ? next.add(r.id) : next.delete(r.id)); return next })} /></th><th>ROW / STATUS</th>{dataset.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead><tbody>{pageRows.map(row => {
            const issues = issuesByRow.get(row.id) ?? [], status = issues.some(i => i.severity === 'error') ? 'error' : issues.length || duplicates.has(row.id) ? 'warning' : 'valid'
            return <tr key={row.id} className={`csv-row-${status}`}><td><input type="checkbox" aria-label={`Select row ${row.id + 1}`} checked={selected.has(row.id)} onChange={e => setSelected(previous => { const next = new Set(previous); if (e.target.checked) next.add(row.id); else next.delete(row.id); return next })} /></td><td><strong>{row.id + 1}</strong><small className={`csv-status csv-status-${status}`}>{status.toUpperCase()}</small></td>{row.cells.map((cell, i) => <td key={i} title={issues.filter(issue => issue.column === i).map(issue => issue.problem).join('; ')}>
              {editing?.id === row.id && editing.column === i ? <EditableCsvCell key={`${row.id}-${i}`} initial={editing.value} label={`Edit ${dataset.headers[i]} row ${row.id + 1}`} onSave={value => change(rows.map(r => r.id === row.id ? { ...r, cells: r.cells.map((c, j) => j === i ? value : c) } : r))} onCancel={() => setEditing(null)} /> : <button className="csv-cell" onClick={() => setEditing({ id: row.id, column: i, value: cell })} aria-label={`Edit ${dataset.headers[i]} row ${row.id + 1}: ${cell || 'empty'}`}>{cell || <em>empty</em>}</button>}
            </td>)}</tr>
          })}</tbody></table></div><div className="csv-toolbar"><button disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>PREVIOUS</button><span>Page {currentPage} / {Math.max(1, Math.ceil(visible.length / PAGE_SIZE))} · {visible.length} matching rows · row numbers follow the original upload</span><button disabled={currentPage * PAGE_SIZE >= visible.length} onClick={() => setPage(currentPage + 1)}>NEXT</button></div>
        </section>
        <section className="admin-info-card"><h2>DUPLICATE REVIEW · {inspection.duplicateGroups.length} GROUPS</h2><p>Only identical rows qualify for bulk deduplication. A shared email can belong to different people. Select records in the table to remove specific rows; changes always have a preview.</p>
          <button onClick={() => { const next = deduplicateExact(rows); const kept = new Set(next.map(r => r.id)); setOperation({ label: 'Keep the first occurrence of each identical row', rows: next, affected: rows.filter(r => !kept.has(r.id)).map(r => r.id) }) }}>PREVIEW SAFE DEDUPLICATION</button>
          {inspection.duplicateGroups.slice((groupPage - 1) * 20, groupPage * 20).map((g, i) => <details key={`${groupPage}-${i}`}><summary>{g.reason} · {g.row_ids.length} rows</summary><div className="csv-toolbar"><button onClick={() => { const ids = new Set(g.row_ids.filter(id => !selected.has(id))); removeRows(ids, 'Keep selected records from this duplicate group; remove its unselected rows') }} disabled={!g.row_ids.some(id => selected.has(id))}>PREVIEW KEEP SELECTED IN GROUP</button></div><div className="csv-group-records">{g.row_ids.map(id => <div key={id}><label><input type="checkbox" checked={selected.has(id)} onChange={e => setSelected(previous => { const next = new Set(previous); if (e.target.checked) next.add(id); else next.delete(id); return next })} /> {title(id)}</label><span>{byId.get(id)?.cells.join(' · ')}</span></div>)}</div></details>)}
          {inspection.duplicateGroups.length > 20 && <div className="csv-toolbar"><button disabled={groupPage === 1} onClick={() => setGroupPage(groupPage - 1)}>PREVIOUS GROUPS</button><span>{groupPage} / {Math.ceil(inspection.duplicateGroups.length / 20)}</span><button disabled={groupPage * 20 >= inspection.duplicateGroups.length} onClick={() => setGroupPage(groupPage + 1)}>NEXT GROUPS</button></div>}
        </section>
        <section className="admin-info-card"><h2>VALIDATION & CORRECTIONS · {displayedIssues.length}</h2><p>Accept or reject each suggestion, or edit the value manually. Missing addresses and ambiguous department abbreviations are never guessed. Rejecting a suggestion does not make an invalid row eligible.</p>
          {!displayedIssues.length && <p>No outstanding validation messages. The import preview performs full server validation.</p>}
          {displayedIssues.slice((currentIssuePage - 1) * PAGE_SIZE, currentIssuePage * PAGE_SIZE).map((issue, i) => <div className={`csv-issue csv-row-${issue.severity}`} key={`${issueKey(issue)}-${i}`}><strong>{title(issue.row_id)} · {issue.severity.toUpperCase()}</strong><p>{issue.problem}{issue.column !== null && ` · ${dataset.headers[issue.column]}`} · Value: <code>{issue.value || '(empty)'}</code>{issue.suggestion !== null && <> · Suggested: <code>{issue.suggestion || '(empty)'}</code></>}</p><div className="certificate-actions">{issue.suggestion !== null && <button onClick={() => setOperation({ label: `Accept correction: ${issue.problem}`, rows: rows.map(r => r.id === issue.row_id ? { ...r, cells: r.cells.map((c, j) => j === issue.column ? issue.suggestion! : c) } : r), affected: [issue.row_id] })}>PREVIEW ACCEPT</button>}<button onClick={() => setRejected(new Set([...rejected, issueKey(issue)]))}>REJECT SUGGESTION</button>{issue.column !== null && <button onClick={() => editCell(issue.row_id, issue.column!)}>EDIT CELL</button>}</div></div>)}
          {displayedIssues.length > PAGE_SIZE && <div className="csv-toolbar"><button disabled={currentIssuePage === 1} onClick={() => setIssuePage(currentIssuePage - 1)}>PREVIOUS WARNINGS</button><span>{currentIssuePage} / {Math.ceil(displayedIssues.length / PAGE_SIZE)}</span><button disabled={currentIssuePage * PAGE_SIZE >= displayedIssues.length} onClick={() => setIssuePage(currentIssuePage + 1)}>NEXT WARNINGS</button></div>}
        </section>
        <section className="admin-info-card"><h2>IMPORT PREVIEW</h2><button className="button button-dark" disabled={!!editing || !!operation} onClick={() => { setPreviewPage(1); void run(() => reviewImport()) }}>SAVE & REVIEW IMPORT →</button><p>Only eligible rows are imported. Shared email rows need individual approval. Imports add membership; editing this draft does not remove previously linked participants. Existing participant IDs and their campaign history are preserved.</p>
          {preview && <><div className="csv-counts"><strong>Total {preview.total}</strong><strong>Valid {preview.valid}</strong><strong>Invalid {preview.invalid}</strong><strong>Duplicates {preview.duplicates}</strong><strong>Needs approval {preview.review}</strong><strong>Modified {preview.modified}</strong><strong>Removed {preview.removed}</strong><strong>Ready {preview.ready}</strong></div>
            <div className="csv-import-plan participant-table-wrap"><table className="participants-table"><thead><tr><th>APPROVE SHARED EMAIL</th><th>ROW / PARTICIPANT</th><th>STATUS / REASON</th></tr></thead><tbody>{preview.rows.slice((previewPage - 1) * PAGE_SIZE, previewPage * PAGE_SIZE).map(r => <tr key={r.row_id}><td>{(r.status === 'REVIEW' || approved.includes(r.row_id)) && <input type="checkbox" aria-label={`Approve shared email row ${r.row_id + 1}`} checked={approved.includes(r.row_id)} onChange={e => { const next = e.target.checked ? [...approved, r.row_id] : approved.filter(id => id !== r.row_id); void run(() => reviewImport(next)) }} />}</td><td>{r.row_id + 1} · {r.name}<small>{r.email}</small></td><td>{r.status}<small>{r.reason}</small></td></tr>)}</tbody></table></div>
            <div className="csv-toolbar"><button disabled={previewPage === 1} onClick={() => setPreviewPage(previewPage - 1)}>PREVIOUS ROWS</button><span>Import page {previewPage} / {Math.max(1, Math.ceil(preview.rows.length / PAGE_SIZE))}</span><button disabled={previewPage * PAGE_SIZE >= preview.rows.length} onClick={() => setPreviewPage(previewPage + 1)}>NEXT ROWS</button></div><button className="button button-dark" disabled={!preview.ready || dirty} onClick={() => void run(async () => { const result = await api.importDataset(dataset.id, preview.digest, approved); const saved = await api.dataset(dataset.id); setDataset(saved); setPreview(null); await refreshList(); setMessage(`${result.eligible} eligible rows processed · ${result.linked} newly linked to this dataset · ${result.reused} existing participants reused. Other datasets and history are preserved.`) })}>IMPORT {preview.ready} ELIGIBLE ROWS →</button><button onClick={() => setPreview(null)}>CANCEL IMPORT</button>
          </>}
        </section>
      </fieldset>}
    </fieldset>
    {operation && <div className="csv-modal-backdrop"><section className="admin-info-card csv-modal" role="dialog" aria-modal="true" aria-label="Preview dataset changes"><h2>{operation.label}</h2><p>{operation.affected.length} rows affected. The original CSV and imported participant records are preserved.</p><div className="participant-table-wrap"><table className="participants-table"><thead><tr><th>ROW</th><th>BEFORE</th><th>AFTER</th></tr></thead><tbody>{operation.affected.slice(0, 50).map(id => <tr key={id}><td>{id + 1}</td><td>{byId.get(id)?.cells.join(' | ')}</td><td>{operation.rows.find(r => r.id === id)?.cells.join(' | ') ?? 'Removed from draft'}</td></tr>)}</tbody></table></div>{operation.affected.length > 50 && <p>Showing the first 50 affected rows.</p>}<div className="certificate-actions"><button onClick={() => setOperation(null)}>CANCEL</button><button disabled={!operation.affected.length || busy} onClick={() => change(operation.rows)}>APPLY {operation.affected.length} CHANGES</button></div></section></div>}
  </>
}
