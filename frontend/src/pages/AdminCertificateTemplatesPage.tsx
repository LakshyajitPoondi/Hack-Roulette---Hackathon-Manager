import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type PointerEvent } from 'react'
import { Link } from 'react-router-dom'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api, certificatePdf } from '../services/api'
import { apiUrl } from '../config/env'
import type { CertificateFont, CertificateTemplate, FontStyle } from '../types/certificate'

GlobalWorkerOptions.workerSrc = workerUrl
type Field = 'name' | 'college' | 'team'
const fieldLabels: Record<Field, { legend: string; sample: string }> = {
  name: { legend: 'Participant name', sample: 'SAMPLE PARTICIPANT NAME' },
  college: { legend: 'College name', sample: 'SAMPLE COLLEGE NAME' },
  team: { legend: 'Team name', sample: 'SAMPLE TEAM NAME' },
}

function styleName(bold: boolean, italic: boolean): FontStyle {
  return bold && italic ? 'bold_italic' : bold ? 'bold' : italic ? 'italic' : 'regular'
}

// Registers the same TTF files the PDF embeds. The browser downloads a face only once text uses it.
const registeredFaces = new Set<string>()
function registerPreviewFonts(fonts: CertificateFont[]) {
  for (const font of fonts) {
    for (const [style, path] of Object.entries(font.preview_files)) {
      const key = `${font.key}:${style}`
      if (registeredFaces.has(key)) continue
      registeredFaces.add(key)
      document.fonts.add(new FontFace(`cert-${font.key}`, `url(${apiUrl}${path})`, {
        weight: style.startsWith('bold') ? '700' : '400', style: style.endsWith('italic') ? 'italic' : 'normal' }))
    }
  }
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
  const [fonts, setFonts] = useState<CertificateFont[]>([])
  const [, setFontsLoaded] = useState(0) // re-render (and re-measure baselines) when a font face finishes loading
  const [baselines, setBaselines] = useState<Record<Field, number>>({ name: 0, college: 0, team: 0 })
  const baselineMarkers = useRef<Partial<Record<Field, HTMLSpanElement | null>>>({})
  const template = templates.find(item => item.id === selectedId)

  useEffect(() => {
    api.certificateFonts().then(items => { registerPreviewFonts(items); setFonts(items) }).catch(err => setError(err.message))
    const loaded = () => setFontsLoaded(value => value + 1)
    document.fonts.addEventListener('loadingdone', loaded)
    return () => document.fonts.removeEventListener('loadingdone', loaded)
  }, [])
  // The PDF draws text on its baseline at the saved point, so each preview label is lifted by its measured baseline.
  useLayoutEffect(() => {
    const next = { name: 0, college: 0, team: 0 }
    for (const field of ['name', 'college', 'team'] as const) next[field] = baselineMarkers.current[field]?.offsetTop ?? 0
    setBaselines(previous => (['name', 'college', 'team'] as const).every(field => previous[field] === next[field]) ? previous : next)
  })

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
  const fontFor = (field: Field) => fonts.find(font => font.key === template?.[`${field}_font_family`])
  function previewFamily(field: Field) {
    const font = fontFor(field)
    if (!font) return 'Arial, Helvetica, sans-serif'
    return Object.keys(font.preview_files).length ? `"cert-${font.key}", ${font.preview_fallback}` : font.preview_fallback
  }
  function changeFamily(field: Field, family: string) {
    if (!template) return
    const styles = fonts.find(font => font.key === family)?.styles ?? []
    let bold = template[`${field}_bold`], italic = template[`${field}_italic`]
    // Keep the chosen style when the new family has it; otherwise drop italic, then bold.
    if (!styles.includes(styleName(bold, italic))) italic = styles.includes(styleName(bold, false)) ? false : italic
    if (!styles.includes(styleName(bold, italic))) { bold = false; italic = styles.includes('italic') && italic }
    edit({ [`${field}_font_family`]: family, [`${field}_bold`]: bold, [`${field}_italic`]: italic })
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
          {(['name', 'college', 'team'] as const).filter(field => field === 'name' || template[`include_${field}`]).map(field => <span key={field} className="certificate-drag-text" onPointerDown={event => drag(event, field)} onPointerMove={event => { if (event.buttons) drag(event, field) }} onPointerUp={event => finishDrag(event, field)} style={{ left: `${template[`${field}_x`]}%`, top: `${template[`${field}_y`]}%`, fontSize: `${template[`${field}_font_size`] * scale}px`, color: template[`${field}_color`], transform: `translate(${template[`${field}_alignment`] === 'center' ? '-50%' : template[`${field}_alignment`] === 'right' ? '-100%' : '0'}, ${-baselines[field]}px)`, fontFamily: previewFamily(field), fontWeight: template[`${field}_bold`] ? 700 : 400, fontStyle: template[`${field}_italic`] ? 'italic' : 'normal' }}>{fieldLabels[field].sample}<span className="baseline-marker" ref={element => { baselineMarkers.current[field] = element }} /></span>)}
        </div>
        <div className="certificate-control-grid">{(['name', 'college', 'team'] as const).map(field => <fieldset key={field}><legend>{fieldLabels[field].legend}</legend>{field !== 'name' && <label className="include-check"><input type="checkbox" checked={template[`include_${field}`]} onChange={event => edit({ [`include_${field}`]: event.target.checked })} /> {field === 'college' ? 'Include College Name' : 'Include Team Name'}</label>}<label>Font family<select value={template[`${field}_font_family`]} onChange={event => changeFamily(field, event.target.value)}>{fonts.length === 0 && <option value={template[`${field}_font_family`]}>{template[`${field}_font_family`]}</option>}{[...new Set(fonts.map(font => font.category))].map(category => <optgroup key={category} label={category}>{fonts.filter(font => font.category === category).map(font => <option key={font.key} value={font.key}>{font.label}</option>)}</optgroup>)}</select></label>{(() => {
          const styles = fontFor(field)?.styles ?? []
          const bold = template[`${field}_bold`], italic = template[`${field}_italic`]
          return <div className="style-checks"><label className="include-check"><input type="checkbox" checked={bold} disabled={!styles.includes(styleName(!bold, italic))} onChange={event => edit({ [`${field}_bold`]: event.target.checked })} /> Bold</label><label className="include-check"><input type="checkbox" checked={italic} disabled={!styles.includes(styleName(bold, !italic))} onChange={event => edit({ [`${field}_italic`]: event.target.checked })} /> Italic</label>{styles.length === 1 && <small>Regular style only</small>}{styles.length > 1 && styles.length < 4 && <small>No italic style</small>}</div>
        })()}<label>Font size<input type="number" min="8" max="200" value={template[`${field}_font_size`]} onChange={event => edit({ [`${field}_font_size`]: Number(event.target.value) })} /></label><label>Alignment<select value={template[`${field}_alignment`]} onChange={event => edit({ [`${field}_alignment`]: event.target.value })}><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></label><label>Color<input type="color" value={template[`${field}_color`]} onChange={event => edit({ [`${field}_color`]: event.target.value })} /></label></fieldset>)}</div>
        <div className="certificate-actions"><button disabled={busy} onClick={() => void act(() => api.updateTemplate(template.id, template), 'Placement saved.')} type="button">SAVE PLACEMENT</button><button type="button" onClick={() => void certificatePdf(`/api/certificates/templates/${template.id}/preview`).catch(err => setError(err.message))}>PREVIEW FINAL PDF</button>{!template.is_active && uploadedId !== template.id ? <button type="button" onClick={() => void act(() => api.activateTemplate(template.id), 'Template is now active.')}>SET AS ACTIVE</button> : template.is_active ? <strong>ACTIVE TEMPLATE</strong> : null}</div>
      </>}
    </section>}
  </>
}
