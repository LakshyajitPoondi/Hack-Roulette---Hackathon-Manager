export type AttendanceStatus = 'REGISTERED' | 'PRESENT' | 'ABSENT'
export interface CsvParticipant { id: number; name: string; email: string; team_name: string | null; college: string | null; created_at: string }
export interface CsvParticipantPage { source: 'csv'; items: CsvParticipant[]; page: number; page_size: number; total: number; total_pages: number }
// A participant already holding a row's email: an existing record, or an earlier row of the same CSV.
export interface CsvMatch { source: 'existing' | 'csv'; id: number | null; line: number | null; name: string; email: string; team_name: string | null; college: string | null }
export interface CsvPreviewRow { line: number; name: string; email: string; team_name: string; college: string; status: 'VALID' | 'REVIEW' | 'DUPLICATE' | 'INVALID'; reason: string; matches: CsvMatch[] }
export interface CsvPreview { digest: string; rows: CsvPreviewRow[]; valid: number; review: number; duplicates: number; invalid: number }
export interface CsvImportResult { imported: number; imported_new: number; imported_reviewed: number; review_skipped: number; duplicates: number; invalid: number }
export type ParticipantInput = Pick<CsvParticipant, 'name' | 'email' | 'team_name' | 'college'> & { allow_shared_email?: boolean }
export type BulkAction = 'MARK_PRESENT' | 'MARK_ABSENT' | 'MARK_ELIGIBLE' | 'MARK_INELIGIBLE'

export interface Participant {
  id: number
  full_name: string
  email: string
  phone: string | null
  college: string | null
  department: string | null
  year: string | null
  team_name: string | null
  registration_source: 'GOOGLE_FORM'
  registration_timestamp: string
  attendance_status: AttendanceStatus
  certificate_eligible: boolean
  is_disqualified: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export interface ParticipantPage {
  items: Participant[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface ParticipantFilters {
  search?: string
  attendance?: AttendanceStatus | ''
  certificate_eligible?: 'true' | 'false' | ''
  college?: string
  year?: string
  is_disqualified?: 'true' | 'false' | ''
  sort_by?: 'name' | 'registration_date' | 'college' | 'team'
  sort_dir?: 'asc' | 'desc'
}

export interface FilterOptions {
  colleges: string[]
  years: string[]
}

export type ParticipantChanges = Partial<Pick<Participant, 'full_name' | 'email' | 'phone' | 'college' | 'department' | 'year' | 'attendance_status' | 'certificate_eligible' | 'is_disqualified' | 'notes'>> & { team_name?: string | null }
