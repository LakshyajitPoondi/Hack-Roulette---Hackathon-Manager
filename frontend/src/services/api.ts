import { apiUrl } from '../config/env'
import type { AdminUser, DashboardData, Role } from '../types/admin'
import type { BulkAction, FilterOptions, Participant, ParticipantChanges, ParticipantFilters, ParticipantPage, CsvParticipant, CsvParticipantPage, CsvPreview, CsvImportResult, ParticipantInput } from '../types/participant'
import type { CertificateFont, CertificateRow, CertificateTemplate } from '../types/certificate'
import type { Campaign, CampaignInput, EmailTemplate, RecipientSelection, RecipientSummary } from '../types/email'
import type { Dataset, DatasetPreview, DatasetRow, DatasetSummary } from '../types/dataset'
import type { CertificateExport, ExportInput } from '../types/certificateExport'
import { ExportStoppedError } from './certificateExport'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

const unauthorizedListeners = new Set<() => void>()

export function onUnauthorized(listener: () => void) {
  unauthorizedListeners.add(listener)
  return () => { unauthorizedListeners.delete(listener) }
}

function unavailable(path: string) {
  return path.startsWith('/api/certificates') ? 'Certificate API unavailable. Check the backend connection.' : 'Backend unavailable. Check the API deployment or local server.'
}

async function failure(response: Response, path: string): Promise<ApiError> {
  const body = await response.json().catch(() => null)
  if (typeof body?.detail === 'string') return new ApiError(response.status, body.detail)
  if (response.status === 404 && !body) return new ApiError(404, `API route unavailable: ${path}`)
  return new ApiError(response.status, `API request failed (${response.status}).`)
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiUrl}${path}`, {
      ...options,
      credentials: 'include',
      headers: options.body instanceof FormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    throw new ApiError(0, unavailable(path))
  }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login' && path !== '/api/auth/me') {
      unauthorizedListeners.forEach(listener => listener())
    }
    throw await failure(response, path)
  }
  return response.status === 204 ? undefined as T : response.json()
}

export const api = {
  createCertificateExport: (input: ExportInput) => request<CertificateExport>('/api/certificates/exports', { method: 'POST', body: JSON.stringify(input), cache: 'no-store' }),
  deleteCertificateExport: (id: string) => request<void>(`/api/certificates/exports/${id}`, { method: 'DELETE', keepalive: true }),
  datasets: () => request<DatasetSummary[]>('/api/datasets'),
  dataset: (id: number) => request<Dataset>(`/api/datasets/${id}`),
  uploadDataset: (name: string, file: File) => { const body = new FormData(); body.set('name', name); body.set('file', file); return request<Dataset>('/api/datasets', { method: 'POST', body }) },
  renameDataset: (id: number, name: string) => request<DatasetSummary>(`/api/datasets/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  archiveDataset: (id: number, archived: boolean) => request<DatasetSummary>(`/api/datasets/${id}/archive?archived=${archived}`, { method: 'POST' }),
  saveDataset: (id: number, revision: number, rows: DatasetRow[]) => request<Dataset>(`/api/datasets/${id}/draft`, { method: 'PATCH', body: JSON.stringify({ revision, rows }) }),
  previewDataset: (id: number, approved_rows: number[] = []) => request<DatasetPreview>(`/api/datasets/${id}/preview`, { method: 'POST', body: JSON.stringify({ approved_rows }) }),
  importDataset: (id: number, digest: string, approved_rows: number[]) => request<{ linked: number; reused: number; eligible: number }>(`/api/datasets/${id}/import`, { method: 'POST', body: JSON.stringify({ digest, approved_rows }) }),
  login: (email: string, password: string) => request<{ user: AdminUser }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  me: () => request<AdminUser>('/api/auth/me'),
  dashboard: () => request<DashboardData>('/api/admin/dashboard'),
  users: () => request<AdminUser[]>('/api/admin/users'),
  createUser: (data: { name: string; email: string; password: string; role: Role }) => request<AdminUser>('/api/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id: number, data: { role?: Role; is_active?: boolean }) => request<AdminUser>(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  disableUser: (id: number) => request<void>(`/api/admin/users/${id}`, { method: 'DELETE' }),
  changePassword: (data: { current_password: string; new_password: string; confirm_new_password: string }) => request<void>('/api/auth/change-password', { method: 'POST', body: JSON.stringify(data) }),
  participants: (filters: ParticipantFilters, page: number, pageSize = 50) => request<ParticipantPage>(`/api/participants?${participantParams(filters, page, pageSize)}`),
  csvParticipants: (search = '', sortBy = 'name', sortDir = 'asc', page = 1, datasetId?: number) => request<CsvParticipantPage>(`/api/participants?${new URLSearchParams({ search, sort_by: sortBy, sort_dir: sortDir, page: String(page), page_size: '50', ...(datasetId ? { dataset_id: String(datasetId) } : {}) })}`),
  allCsvParticipants: (datasetId?: number) => request<CsvParticipant[]>(`/api/participants/all${datasetId ? `?dataset_id=${datasetId}` : ''}`),
  updateCsvParticipant: (id: number, changes: ParticipantInput) => request<CsvParticipant>(`/api/participants/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  createCsvParticipant: (person: ParticipantInput) => request<CsvParticipant>('/api/participants', { method: 'POST', body: JSON.stringify(person) }),
  previewCsv: (file: File) => { const body = new FormData(); body.set('file', file); return request<CsvPreview>('/api/participants/import/preview', { method: 'POST', body }) },
  importCsv: (file: File, digest: string, approvedLines: number[] = []) => { const body = new FormData(); body.set('file', file); body.set('digest', digest); body.set('approved_lines', approvedLines.join(',')); return request<CsvImportResult>('/api/participants/import', { method: 'POST', body }) },
  deleteCsvParticipant: (id: number) => request<void>(`/api/participants/${id}`, { method: 'DELETE' }),
  clearCsvParticipants: () => request<void>('/api/participants/clear', { method: 'DELETE' }),
  participantOptions: () => request<FilterOptions>('/api/participants/options'),
  participant: (id: number) => request<Participant>(`/api/participants/${id}`),
  updateParticipant: (id: number, changes: ParticipantChanges) => request<Participant>(`/api/participants/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  bulkParticipants: (participant_ids: number[], action: BulkAction) => request<{ updated_count: number }>('/api/participants/bulk-update', { method: 'POST', body: JSON.stringify({ participant_ids, action }) }),
  templates: () => request<CertificateTemplate[]>('/api/certificates/templates'),
  certificateFonts: () => request<CertificateFont[]>('/api/certificates/fonts'),
  manualStatus: () => request<{ template_ready: boolean; email_mode: string; brevo_configured: boolean }>('/api/email/manual/status'),
  manualSend: (data: { to: string; participant_name: string; college_name: string; subject: string; body: string; attach_certificate: boolean }) => request<{ recipient: string; message_id: string; status: string }>('/api/email/manual/send', { method: 'POST', body: JSON.stringify(data) }),
  uploadTemplate: (name: string, file: File) => { const body = new FormData(); body.set('name', name); body.set('file', file); return request<CertificateTemplate>('/api/certificates/templates', { method: 'POST', body }) },
  updateTemplate: (id: number, changes: Partial<CertificateTemplate>) => request<CertificateTemplate>(`/api/certificates/templates/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  activateTemplate: (id: number) => request<CertificateTemplate>(`/api/certificates/templates/${id}/activate`, { method: 'POST' }),
  replaceTemplate: (id: number, file: File) => { const body = new FormData(); body.set('file', file); return request<CertificateTemplate>(`/api/certificates/templates/${id}/replace`, { method: 'POST', body }) },
  deleteTemplate: (id: number) => request<void>(`/api/certificates/templates/${id}`, { method: 'DELETE' }),
  certificates: (params: URLSearchParams) => request<{ items: CertificateRow[]; total: number; page: number; page_size: number }>(`/api/certificates?${params}`),
  participantCertificate: (id: number) => request<CertificateRow>(`/api/certificates/participants/${id}`),
  emailMode: () => request<{ mode: string; sending_enabled: boolean }>('/api/email/mode'),
  emailTemplates: () => request<EmailTemplate[]>('/api/email/templates'),
  createEmailTemplate: (data: Pick<EmailTemplate, 'name' | 'subject' | 'body'>) => request<EmailTemplate>('/api/email/templates', { method: 'POST', body: JSON.stringify(data) }),
  updateEmailTemplate: (id: number, data: Partial<Pick<EmailTemplate, 'name' | 'subject' | 'body'>>) => request<EmailTemplate>(`/api/email/templates/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteEmailTemplate: (id: number) => request<void>(`/api/email/templates/${id}`, { method: 'DELETE' }),
  emailPreview: (subject: string, body: string, participant_id?: number, attach_certificate = false, certificate_template_id?: number) => request<{ subject: string; body: string }>('/api/email/preview', { method: 'POST', body: JSON.stringify({ name: 'Preview', subject, body, participant_id, attach_certificate, certificate_template_id }) }),
  emailTest: (data: { to: string; sender_name: string; reply_to: string | null; subject: string; body: string; participant_id?: number; attach_certificate?: boolean; certificate_template_id?: number }) => request<{ recipient: string; message_id: string; mode: string }>('/api/email/test', { method: 'POST', body: JSON.stringify(data) }),
  recipientSummary: (data: RecipientSelection) => request<RecipientSummary>('/api/email/recipients/summary', { method: 'POST', body: JSON.stringify(data) }),
  createCampaign: (data: CampaignInput) => request<{ id: number; status: string; recipients: number; skipped_invalid: number }>('/api/email/campaigns', { method: 'POST', body: JSON.stringify(data) }),
  campaigns: () => request<Campaign[]>('/api/email/campaigns'),
  campaign: (id: number) => request<Campaign>(`/api/email/campaigns/${id}`),
  continueCampaign: (id: number) => request<{ status: string; processed: number }>(`/api/email/campaigns/${id}/continue`, { method: 'POST' }),
  retryCampaign: (id: number) => request<{ retried: number; status: string }>(`/api/email/campaigns/${id}/retry`, { method: 'POST' }),
}

export async function fetchExportPdf(exportId: string, participantId: number, signal: AbortSignal) {
  const path = `/api/certificates/exports/${exportId}/participants/${participantId}`
  let response: Response
  try { response = await fetch(`${apiUrl}${path}`, { credentials: 'include', cache: 'no-store', signal }) }
  catch { throw new ExportStoppedError(signal.aborted ? 'Generation stopped.' : 'Connection lost. Check your connection and start a new run.') }
  if (!response.ok) {
    const error = await failure(response, path)
    if (response.status === 401) unauthorizedListeners.forEach(listener => listener())
    if ([401, 403, 404].includes(response.status)) throw new ExportStoppedError(error.message)
    throw error
  }
  return new Uint8Array(await response.arrayBuffer())
}

export async function downloadDataset(id: number, original = false) {
  const path = `/api/datasets/${id}/export?original=${original}`
  const response = await fetch(`${apiUrl}${path}`, { credentials: 'include' })
  if (!response.ok) throw await failure(response, path)
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `dataset-${id}${original ? '-original.txt' : '.csv'}`; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function finishCampaign(id: number, initialStatus: string) {
  let status = initialStatus
  while (status === 'PROCESSING') {
    const next = await api.continueCampaign(id)
    if (next.processed === 0 && next.status === 'PROCESSING') throw new Error('Sending paused. Open the campaign to resume pending recipients.')
    status = next.status
  }
  return status
}

export async function certificatePdf(path: string, download = false) {
  const previewTab = download ? null : window.open('', '_blank')
  let response: Response
  try { response = await fetch(`${apiUrl}${path}`, { credentials: 'include' }) }
  catch { previewTab?.close(); throw new ApiError(0, unavailable(path)) }
  if (!response.ok) {
    previewTab?.close()
    throw await failure(response, path)
  }
  const url = URL.createObjectURL(await response.blob())
  if (download) {
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'certificate.pdf'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } else {
    if (previewTab) previewTab.location.href = url
    else window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 120000)
  }
}

export async function manualCertificatePdf(participant_name: string, college_name: string, team_name: string, download = false) {
  const previewTab = download ? null : window.open('', '_blank')
  let response: Response
  try { response = await fetch(`${apiUrl}/api/certificates/manual?download=${download}`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ participant_name, college_name, team_name }) }) }
  catch { previewTab?.close(); throw new ApiError(0, unavailable('/api/certificates/manual')) }
  if (!response.ok) { previewTab?.close(); throw await failure(response, '/api/certificates/manual') }
  const url = URL.createObjectURL(await response.blob())
  if (download) { const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'certificate.pdf'; anchor.click() }
  else if (previewTab) previewTab.location.href = url
  else window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 120000)
}

export function participantParams(filters: ParticipantFilters, page?: number, pageSize?: number) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, value) })
  if (page !== undefined) params.set('page', String(page))
  if (pageSize !== undefined) params.set('page_size', String(pageSize))
  return params.toString()
}

export async function exportParticipants(filters: ParticipantFilters) {
  let response: Response
  try { response = await fetch(`${apiUrl}/api/participants/export?${participantParams(filters)}`, { credentials: 'include' }) }
  catch { throw new ApiError(0, unavailable('/api/participants/export')) }
  if (!response.ok) throw await failure(response, '/api/participants/export')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'tech-roulette-participants.csv'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
