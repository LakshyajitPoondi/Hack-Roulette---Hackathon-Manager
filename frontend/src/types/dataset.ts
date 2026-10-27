export interface DatasetRow { id: number; cells: string[] }
export interface DatasetSummary { id: number; name: string; original_filename: string; created_at: string; participant_count: number; archived: boolean; revision: number; is_legacy: boolean }
export interface CsvIssue { row_id: number; column: number | null; severity: 'error' | 'warning'; problem: string; value: string; suggestion: string | null }
export interface DuplicateGroup { reason: string; row_ids: number[]; safe: boolean }
export interface Dataset extends DatasetSummary { headers: string[]; rows: DatasetRow[]; original_rows: DatasetRow[]; issues: CsvIssue[]; duplicate_groups: DuplicateGroup[] }
export interface DatasetPreview { digest: string; total: number; valid: number; invalid: number; duplicates: number; review: number; modified: number; removed: number; ready: number; rows: { row_id: number; status: 'READY' | 'INVALID' | 'DUPLICATE' | 'REVIEW'; reason: string; participant_id: number | null; name: string; email: string; team_name: string; college: string }[] }
