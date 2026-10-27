import { Zip, ZipPassThrough } from 'fflate'
import type { CertificateExport, ExportFailure, ExportProgress, ExportRecipient } from '../types/certificateExport'

export const MAX_ZIP_BYTES = 100 * 1024 * 1024
export class ExportStoppedError extends Error {}

export function selectExportIds(people: { id: number }[], selected: Set<number>, all: boolean) {
  return people.filter(p => all || selected.has(p.id)).map(p => p.id)
}

/** One bounded PDF request at a time, with progress only after a real response/failure. */
export async function generateCertificateZip(
  run: CertificateExport,
  fetchPdf: (recipient: ExportRecipient) => Promise<Uint8Array>,
  onProgress: (progress: ExportProgress) => void,
  maxBytes = MAX_ZIP_BYTES,
) {
  const chunks: ArrayBuffer[] = [], failures: ExportFailure[] = []
  let attempted = 0, generated = 0, bytes = 0, zipError: Error | null = null
  const zip = new Zip((error, chunk) => {
    if (error) zipError = error
    else chunks.push(new Uint8Array(chunk).buffer)
  })
  const report = (phase: ExportProgress['phase']) => onProgress({ phase, attempted, total: run.total, generated, failed: failures.filter(f => f.attempted).length })
  report('generating')
  try {
    for (const [index, recipient] of run.recipients.entries()) {
      let stop = ''
      try {
        const data = await fetchPdf(recipient)
        if (data.byteLength > run.max_pdf_bytes) throw new Error('PDF exceeds the per-file size limit.')
        if (data.byteLength < 5 || String.fromCharCode(...data.subarray(0, 5)) !== '%PDF-') throw new Error('Server returned an invalid PDF.')
        if (bytes + data.byteLength + 1024 > maxBytes) throw new ExportStoppedError('ZIP size limit reached. Generate the remaining participants in a smaller selection.')
        const file = new ZipPassThrough(recipient.filename)
        zip.add(file); file.push(data, true)
        if (zipError) throw new ExportStoppedError('ZIP preparation failed. Start a new generation run.')
        bytes += data.byteLength + 1024
        generated++
      } catch (e) {
        const reason = e instanceof Error ? e.message : 'Certificate generation failed.'
        failures.push({ ...recipient, reason, attempted: true })
        if (e instanceof ExportStoppedError) stop = reason
      }
      attempted++; report('generating')
      if (stop) {
        for (const remaining of run.recipients.slice(index + 1)) failures.push({ ...remaining, reason: `Not generated: ${stop}`, attempted: false })
        break
      }
    }
    if (!generated) return { blob: null, generated, attempted, failures }
    report('packaging')
    // Yield to paint the actual packaging state, rather than displaying artificial progress.
    await new Promise<void>(resolve => setTimeout(resolve, 0))
    zip.end()
    if (zipError) throw new Error('ZIP preparation failed. Please try again.')
    return { blob: new Blob(chunks, { type: 'application/zip' }), generated, attempted, failures }
  } finally { zip.terminate() }
}
