export type AttendanceStatus = 'REGISTERED' | 'PRESENT' | 'ABSENT'
export interface CsvParticipant { id: number; name: string; email: string; team_name: string | null; college: string | null; created_at: string }
export interface CsvParticipantPage { source: 'csv'; items: CsvParticipant[]; page: number; page_size: number; total: number; total_pages: number }
export interface CsvPreviewRow { line: number; name: string; email: string; team_name: string; college: string; status: 'VALID' | 'DUPLICATE' | 'INVALID'; reason: string }
export interface CsvPreview { digest: string; rows: CsvPreviewRow[]; valid: number; duplicates: number; invalid: number }
export interface CsvImportResult { imported: number; duplicates: number; invalid: number }
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
