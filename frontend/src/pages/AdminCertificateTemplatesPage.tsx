import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from 'react'
import { Link } from 'react-router-dom'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api, certificatePdf } from '../services/api'
import { apiUrl } from '../config/env'
import type { CertificateTemplate } from '../types/certificate'

GlobalWorkerOptions.workerSrc = workerUrl
type Field = 'name' | 'college' | 'team'
const fieldLabels: Record<Field, { legend: string; sample: string }> = {
  name: { legend: 'Participant name', sample: 'SAMPLE PARTICIPANT NAME' },
  college: { legend: 'College name', sample: 'SAMPLE COLLEGE NAME' },
  team: { legend: 'Team name', sample: 'SAMPLE TEAM NAME' },
}

export function AdminCertificateTemplatesPage() {
  const [templates, setTemplates] = useState<CertificateTemplate[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [name, setName] = useState('Participation certificate')
  const [file, setFile] = useState<File | null>(null)
  const [uploadedId, setUploadedId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [sourceUrl, setSourceUrl] = useState('')
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 })
  const [displayWidth, setDisplayWidth] = useState(1)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const template = templates.find(item => item.id === selectedId)

  useEffect(() => { api.templates().then(items => { setTemplates(items); setSelectedId(id => id && items.some(item => item.id === id) ? id : (items.find(item => item.is_active) || items[0])?.id || null) }).catch(err => setError(err.message)) }, [revision])
  useEffect(() => {
    if (!template) return
    let cancelled = false
    let url = ''
    async function load() {
      try {
        const response = await fetch(`${apiUrl}/api/certificates/templates/${template!.id}/file`, { credentials: 'include' })
        if (!response.ok) throw new Error('Certificate template could not be loaded.')
        const data = await response.arrayBuffer()
        if (cancelled) return
        if (template!.file_type === 'pdf') {
          const doc = await getDocument({ data }).promise
          const page = await doc.getPage(1)
          const viewport = page.getViewport({ scale: 1 })
          const canvas = canvasRef.current!
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          await page.render({ canvas, canvasContext: canvas.getContext('2d')!, viewport }).promise
          if (!cancelled) setDimensions({ width: viewport.width, height: viewport.height })
          await doc.destroy()
        } else {
          url = URL.createObjectURL(new Blob([data], { type: template!.file_type === 'png' ? 'image/png' : 'image/jpeg' }))
          const image = new Image()
          image.onload = () => { if (!cancelled) { setDimensions({ width: image.naturalWidth, height: image.naturalHeight }); setSourceUrl(url) } }
          image.src = url
        }
        setError('')
      } catch (err) { if (!cancelled) setError(err instanceof Error ? err.message : 'Template preview failed') }
    }
    void load()
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); setSourceUrl('') }
  }, [template?.id, template?.file_type, revision])
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const observer = new ResizeObserver(() => setDisplayWidth(stage.clientWidth))
    observer.observe(stage)
    return () => observer.disconnect()
  }, [template?.id])

  async function act(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setMessage('')
    try { await action(); setMessage(success); setRevision(value => value + 1) }
    catch (err) { setError(err instanceof Error ? err.message : 'Action failed') }
    finally { setBusy(false) }
  }
  function upload(event: FormEvent) {
    event.preventDefault()
    if (file) void act(async () => { const created = await api.uploadTemplate(name, file); setSelectedId(created.id); setUploadedId(created.id); setFile(null); if (fileInputRef.current) fileInputRef.current.value = '' }, 'Template uploaded. Drag the text into place, preview, then set it as active.')
  }
  function edit(changes: Partial<CertificateTemplate>) {
    setTemplates(items => items.map(item => item.id === selectedId ? { ...item, ...changes } : item))
    setMessage('Unsaved changes. Select Save placement before testing the PDF.')
  }
  function drag(event: PointerEvent<HTMLSpanElement>, field: Field) {
    const stage = stageRef.current
    if (!stage) return
    event.preventDefault()
    if (event.type === 'pointerdown') event.currentTarget.setPointerCapture(event.pointerId)
    const rect = stage.getBoundingClientRect()
    const x = Math.max(0, Math.min(100, (event.clientX - rect.left) / rect.width * 100))
    const y = Math.max(0, Math.min(100, (event.clientY - rect.top) / rect.height * 100))
    edit({ [`${field}_x`]: x, [`${field}_y`]: y })
  }
  function finishDrag(event: PointerEvent<HTMLSpanElement>, field: Field) {
    if (!template || !stageRef.current) return
    const rect = stageRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(100, (event.clientX - rect.left) / rect.width * 100))
    const y = Math.max(0, Math.min(100, (event.clientY - rect.top) / rect.height * 100))
    api.updateTemplate(template.id, { [`${field}_x`]: x, [`${field}_y`]: y })
      .then(() => setMessage('Position saved.'))
      .catch(err => setError(err instanceof Error ? err.message : 'Position could not be saved'))
  }
  const scale = displayWidth / dimensions.width
  return <>
    <div className="admin-page-heading"><div><span className="eyebrow">/ STEP 3</span><h1>CERTIFICATE TEMPLATE<span>.</span></h1><p>Upload a template, choose and position its labels, preview, then activate it.</p></div><Link className="button button-outline" to="/admin/certificates">TEST CERTIFICATE →</Link></div>
    {error && <div className="form-error" role="alert">{error}</div>}{message && <div className="form-success">{message}</div>}
    <form className="certificate-upload" onSubmit={upload}><h2>STEP 1 / SELECT OR UPLOAD TEMPLATE</h2><label>TEMPLATE NAME<input required value={name} onChange={event => setName(event.target.value)} /></label><div className="certificate-file-row"><label className="button button-outline" htmlFor="certificate-file">CHOOSE FILE<input ref={fileInputRef} id="certificate-file" className="visually-hidden" type="file" accept="image/png,image/jpeg,application/pdf" onChange={event => { setFile(event.target.files?.[0] || null); setUploadedId(null) }} /></label><span>{file?.name || 'No file chosen'}</span></div>{uploadedId ? <button type="button" className="button button-dark" disabled={busy} onClick={() => void act(async () => { await api.activateTemplate(uploadedId); setUploadedId(null) }, 'Template is now active.')}>SET AS ACTIVE →</button> : <button className="button button-dark" disabled={busy || !file}>UPLOAD TEMPLATE →</button>}</form>
    {templates.length > 0 && <section className="certificate-card"><label className="certificate-select-heading">SELECT UPLOADED TEMPLATE<select value={selectedId ?? ''} onChange={event => { setSelectedId(Number(event.target.value)); setUploadedId(null) }}>{templates.map(item => <option key={item.id} value={item.id}>{item.name}{item.is_active ? ' (active)' : ''}</option>)}</select></label>
      {template && <><p className="certificate-help">Drag each sample label on the certificate. Its position is stored as a percentage of the original page, so preview size does not affect the PDF.</p>
        <div className="certificate-stage" ref={stageRef} style={{ aspectRatio: `${dimensions.width} / ${dimensions.height}` }}>
          {template.file_type === 'pdf' ? <canvas ref={canvasRef} /> : <img src={sourceUrl} alt="Certificate template" />}
          {(['name', 'college', 'team'] as const).filter(field => field === 'name' || template[`include_${field}`]).map(field => <span key={field} className="certificate-drag-text" onPointerDown={event => drag(event, field)} onPointerMove={event => { if (event.buttons) drag(event, field) }} onPointerUp={event => finishDrag(event, field)} style={{ left: `${template[`${field}_x`]}%`, top: `${template[`${field}_y`]}%`, fontSize: `${template[`${field}_font_size`] * scale}px`, color: template[`${field}_color`], transform: `translate(${template[`${field}_alignment`] === 'center' ? '-50%' : template[`${field}_alignment`] === 'right' ? '-100%' : '0'}, -100%)`, fontWeight: field === 'name' ? 700 : 400 }}>{fieldLabels[field].sample}</span>)}
        </div>
        <div className="certificate-control-grid">{(['name', 'college', 'team'] as const).map(field => <fieldset key={field}><legend>{fieldLabels[field].legend}</legend>{field !== 'name' && <label className="include-check"><input type="checkbox" checked={template[`include_${field}`]} onChange={event => edit({ [`include_${field}`]: event.target.checked })} /> {field === 'college' ? 'Include College Name' : 'Include Team Name'}</label>}<label>Font size<input type="number" min="8" max="200" value={template[`${field}_font_size`]} onChange={event => edit({ [`${field}_font_size`]: Number(event.target.value) })} /></label><label>Alignment<select value={template[`${field}_alignment`]} onChange={event => edit({ [`${field}_alignment`]: event.target.value })}><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></label><label>Color<input type="color" value={template[`${field}_color`]} onChange={event => edit({ [`${field}_color`]: event.target.value })} /></label></fieldset>)}</div>
        <div className="certificate-actions"><button disabled={busy} onClick={() => void act(() => api.updateTemplate(template.id, template), 'Placement saved.')} type="button">SAVE PLACEMENT</button><button type="button" onClick={() => void certificatePdf(`/api/certificates/templates/${template.id}/preview`).catch(err => setError(err.message))}>PREVIEW FINAL PDF</button>{!template.is_active && uploadedId !== template.id ? <button type="button" onClick={() => void act(() => api.activateTemplate(template.id), 'Template is now active.')}>SET AS ACTIVE</button> : template.is_active ? <strong>ACTIVE TEMPLATE</strong> : null}</div>
      </>}
    </section>}
  </>
}
