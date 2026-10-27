const { test } = require('node:test')
const assert = require('node:assert/strict')
const { unzipSync, strFromU8 } = require('fflate')
const { generateCertificateZip, selectExportIds, ExportStoppedError } = require('../node_modules/.cache/certificate-export-tests/services/certificateExport.js')

const recipients = [
  { id: 1, name: 'Same Name', filename: 'Same_Name_1.pdf' },
  { id: 2, name: 'Same Name', filename: 'Same_Name_2.pdf' },
  { id: 3, name: 'José Živković', filename: 'José_Živković_3.pdf' },
]
const run = { id: 'test', total: recipients.length, recipients, max_pdf_bytes: 3 * 1024 * 1024 }
const data = name => new TextEncoder().encode(`%PDF-1.4\n${name}`)

test('Select All uses all scope rows, including beyond the displayed page; selected uses stable IDs', () => {
  const scope = Array.from({ length: 140 }, (_, i) => ({ id: i + 1 }))
  assert.equal(selectExportIds(scope, new Set(), true).length, 140)
  assert.deepEqual(selectExportIds(scope, new Set([2, 101]), false), [2, 101])
  assert.deepEqual(selectExportIds(scope.slice(0, 50), new Set([101]), false), [])
})

test('ZIP contains distinct PDFs for duplicate names and UTF-8 filenames, with truthful completion', async () => {
  const updates = []
  const result = await generateCertificateZip(run, async p => data(p.name), update => updates.push(update))
  const files = unzipSync(new Uint8Array(await result.blob.arrayBuffer()))
  assert.deepEqual(Object.keys(files), recipients.map(p => p.filename))
  assert.equal(strFromU8(files['José_Živković_3.pdf']), '%PDF-1.4\nJosé Živković')
  assert.equal(result.generated, 3)
  assert.equal(result.failures.length, 0)
  assert.deepEqual(updates.filter(u => u.phase === 'generating').map(u => u.attempted), [0, 1, 2, 3])
  assert.equal(updates.at(-1).phase, 'packaging')
})

test('progress does not advance while the backend is still generating a PDF', async () => {
  let finish
  const updates = []
  const promise = generateCertificateZip({ ...run, total: 1, recipients: recipients.slice(0, 1) }, () => new Promise(resolve => { finish = resolve }), u => updates.push(u))
  await Promise.resolve()
  assert.equal(updates.length, 1)
  assert.equal(updates[0].attempted, 0)
  finish(data('Done'))
  const result = await promise
  assert.equal(result.generated, 1)
  assert.equal(updates.at(-1).attempted, 1)
})

test('partial ZIP includes only successes and reports the exact participant failure', async () => {
  const result = await generateCertificateZip(run, async p => { if (p.id === 2) throw new Error('Rendering failed'); return data(p.name) }, () => {})
  const files = unzipSync(new Uint8Array(await result.blob.arrayBuffer()))
  assert.deepEqual(Object.keys(files), [recipients[0].filename, recipients[2].filename])
  assert.equal(result.failures[0].id, 2)
  assert.equal(result.failures[0].reason, 'Rendering failed')
  assert.equal(result.attempted, 3)
})

test('all failures produce no ZIP, and invalid responses never become PDF entries', async () => {
  const result = await generateCertificateZip(run, async () => new TextEncoder().encode('<html>error</html>'), () => {})
  assert.equal(result.blob, null)
  assert.equal(result.generated, 0)
  assert.equal(result.failures.length, 3)
})

test('authentication/network interruption stops further requests and does not fake 100% progress', async () => {
  const updates = [], calls = []
  const result = await generateCertificateZip(run, async p => { calls.push(p.id); if (p.id === 2) throw new ExportStoppedError('Session expired'); return data(p.name) }, u => updates.push(u))
  assert.deepEqual(calls, [1, 2])
  assert.equal(result.attempted, 2)
  assert.equal(result.failures.find(f => f.id === 3).attempted, false)
  assert.equal(updates.at(-1).attempted, 2)
  assert.equal(Object.keys(unzipSync(new Uint8Array(await result.blob.arrayBuffer()))).length, 1)
})

test('ZIP memory limit stops safely with a partial archive; per-PDF limit reports a failure', async () => {
  const result = await generateCertificateZip(run, async p => data(p.name), () => {}, 1200)
  assert.equal(result.generated, 1)
  assert.equal(result.attempted, 2)
  assert.ok(result.failures[0].reason.includes('ZIP size'))
  const oversized = await generateCertificateZip({ ...run, max_pdf_bytes: 2 }, async p => data(p.name), () => {})
  assert.equal(oversized.blob, null)
  assert.equal(oversized.failures.length, 3)
})
