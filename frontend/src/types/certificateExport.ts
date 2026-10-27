export interface ExportRecipient { id: number; name: string; filename: string }
export interface CertificateExport { id: string; template_id: number; template_name: string; total: number; max_pdf_bytes: number; expires_at: string; recipients: ExportRecipient[] }
export interface ExportInput { request_id: string; selection: 'all' | 'selected'; dataset_id?: number; participant_ids: number[]; template_id: number; expected_count: number }
export interface ExportFailure extends ExportRecipient { reason: string; attempted: boolean }
export interface ExportProgress { phase: 'generating' | 'packaging'; attempted: number; total: number; generated: number; failed: number }
