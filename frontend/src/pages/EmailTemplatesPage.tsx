import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { EmailTemplate } from '../types/email'

const empty = { name: '', subject: '', body: '' }
export function EmailTemplatesPage({ embedded = false }: { embedded?: boolean }) {
  const [templates, setTemplates] = useState<EmailTemplate[]>([])
  const [editing, setEditing] = useState<number | null>(null)
  const [form, setForm] = useState(empty)
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [renaming, setRenaming] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => api.emailTemplates().then(setTemplates).catch(e => setError(e.message))
  useEffect(() => { void load() }, [])
  async function save() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      if (editing) await api.updateEmailTemplate(editing, form)
      else await api.createEmailTemplate(form)
      setForm(empty); setEditing(null); setPreview(null); setMessage('Template saved.'); await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed') }
    finally { setBusy(false) }
  }
  async function renameTemplate(id: number) {
    if (busy) return
    setBusy(true); setError('')
    try { const saved = await api.updateEmailTemplate(id, { name: newName }); setTemplates(items => items.map(item => item.id === id ? saved : item)); if (editing === id) setForm(previous => ({ ...previous, name: saved.name })); setRenaming(null); setMessage('Template renamed. Content and references are preserved.'); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'Rename failed') }
    finally { setBusy(false) }
  }
  async function remove(id: number) {
    if (!window.confirm('Delete this email template? Existing campaigns keep their saved content.')) return
    try { await api.deleteEmailTemplate(id); await load() } catch (e) { setError(e instanceof Error ? e.message : 'Delete failed') }
  }
  async function showPreview() {
    try { setPreview(await api.emailPreview(form.subject, form.body)); setError('') }
    catch (e) { setError(e instanceof Error ? e.message : 'Preview failed') }
  }
  return <>{!embedded && <div className="admin-page-heading"><div><span className="eyebrow">/ EMAIL</span><h1>TEMPLATES<span>.</span></h1><p>Use participant_name and college_name placeholders in double braces.</p></div></div>}
    {error && <div className="form-error" role="alert">{error}</div>}{message && <div className="form-success">{message}</div>}
    <section className="admin-info-card email-form"><h2>{editing ? 'EDIT TEMPLATE' : 'NEW TEMPLATE'}</h2><label>Name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>Subject<input value={form.subject} onChange={e => setForm({ ...form, subject: e.target.value })} /></label><label>Body<textarea rows={8} value={form.body} onChange={e => setForm({ ...form, body: e.target.value })} /></label><div className="certificate-actions"><button onClick={() => void showPreview()}>PREVIEW</button><button onClick={() => void save()}>SAVE TEMPLATE</button>{editing && <button onClick={() => { setEditing(null); setForm(empty) }}>CANCEL EDIT</button>}</div>{preview && <div className="email-preview"><strong>{preview.subject}</strong><pre>{preview.body}</pre></div>}</section>
    <section className="admin-info-card"><h2>SAVED TEMPLATES</h2>{templates.length === 0 && <p>No templates yet.</p>}{templates.map(item => <div className="email-list-row" key={item.id}><div><strong>{item.name}</strong><small>{item.subject}</small>{renaming === item.id && <form className="csv-toolbar" onSubmit={e => { e.preventDefault(); void renameTemplate(item.id) }}><input required aria-label="New email template name" maxLength={160} value={newName} onChange={e => setNewName(e.target.value)} /><button disabled={busy || !newName.trim()}>SAVE NAME</button><button type="button" onClick={() => setRenaming(null)}>CANCEL</button></form>}</div><div className="certificate-actions"><button disabled={busy} onClick={() => { setRenaming(item.id); setNewName(item.name) }}>RENAME</button><button disabled={busy} onClick={() => { setEditing(item.id); setForm({ name: item.name, subject: item.subject, body: item.body }); setPreview(null) }}>EDIT</button><button disabled={busy} onClick={() => void remove(item.id)}>DELETE</button></div></div>)}</section>
  </>
}
