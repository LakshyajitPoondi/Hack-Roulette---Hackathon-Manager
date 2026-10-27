import type { CsvIssue, DatasetRow, DuplicateGroup } from '../types/dataset'

export const headerKey = (value: string) => value.trim().toLowerCase().replace(/[_-]/g, ' ').replace(/\s+/g, ' ')
export const nameColumn = (headers: string[]) => headers.findIndex(h => ['name', 'participant name', 'full name'].includes(headerKey(h)))
export const emailColumn = (headers: string[]) => headers.findIndex(h => ['email', 'email address', 'participant email'].includes(headerKey(h)))
export const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
function departmentKey(value: string) {
  const words = (value.toLowerCase().match(/\p{L}+/gu) ?? []).filter(w => !['and', 'of', 'the', 'department', 'dept'].includes(w))
  return words.length > 1 && words.every(w => w.length >= 3) ? words.map(w => w[0]).join('') : value.toLowerCase().replace(/[^\p{L}\p{N}_]/gu, '')
}

export function replaceValues(rows: DatasetRow[], column: number, find: string, replacement: string, ignoreCase = false) {
  const key = (s: string) => ignoreCase ? s.toLowerCase() : s
  const affected = rows.filter(r => key(r.cells[column]) === key(find) && r.cells[column] !== replacement)
  const ids = new Set(affected.map(r => r.id))
  return { affected, rows: rows.map(r => ids.has(r.id) ? { ...r, cells: r.cells.map((c, i) => i === column ? replacement : c) } : r) }
}

export function sortRows(rows: DatasetRow[], column: number, descending = false) {
  return [...rows].sort((a, b) => (descending ? -1 : 1) * a.cells[column].localeCompare(b.cells[column], undefined, { numeric: true }))
}

export function exactDuplicates(rows: DatasetRow[]) {
  const groups = new Map<string, number[]>()
  rows.forEach(row => { const key = JSON.stringify(row.cells); groups.set(key, [...(groups.get(key) ?? []), row.id]) })
  return [...groups.values()].filter(ids => ids.length > 1)
}

export function deduplicateExact(rows: DatasetRow[]) {
  const seen = new Set<string>()
  return rows.filter(row => { const key = JSON.stringify(row.cells); if (seen.has(key)) return false; seen.add(key); return true })
}

// Immediate editor feedback; authoritative validation and import planning still run on the server.
export function inspectRows(headers: string[], rows: DatasetRow[]) {
  const issues: CsvIssue[] = [], duplicateGroups: DuplicateGroup[] = []
  const names = nameColumn(headers), emails = emailColumn(headers)
  const identity = new Map<string, number[]>(), shared = new Map<string, number[]>()
  const departments = new Map<number, Map<string, { values: Set<string>; ids: number[] }>>()
  headers.forEach((h, i) => { if (['department', 'dept', 'department name'].includes(headerKey(h))) departments.set(i, new Map()) })
  for (const row of rows) {
    const add = (column: number | null, severity: 'error' | 'warning', problem: string, suggestion: string | null = null) => issues.push({ row_id: row.id, column, severity, problem, value: column === null ? '' : row.cells[column], suggestion })
    if (!row.cells.some(c => c.trim())) add(null, 'error', 'Empty row')
    row.cells.forEach((c, i) => {
      if (c !== c.trim()) add(i, 'warning', 'Leading or trailing whitespace', c.trim())
      if (/\t|\n| {2}/.test(c)) add(i, 'warning', 'Suspicious spacing or multiline value')
      if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(c)) add(i, 'error', 'Unexpected control character')
    })
    const name = row.cells[names]?.trim() ?? '', email = row.cells[emails]?.trim() ?? ''
    if (!name) add(names, 'error', 'Missing required name')
    if (!email) add(emails, 'error', 'Missing required email')
    if (email && !emailPattern.test(email)) {
      const compact = email.replace(/\s/g, '')
      add(emails, 'error', 'Invalid email format', compact !== email && emailPattern.test(compact) ? compact : null)
    }
    row.cells.forEach((c, i) => { if ((i === names || i === emails || ['team', 'team name', 'college', 'college name', 'institution'].includes(headerKey(headers[i]))) && c.trim().length > (i === emails ? 320 : 160)) add(i, 'error', 'Value is too long') })
    if (name && email) {
      const key = JSON.stringify([name.toLowerCase().replace(/\s+/g, ' '), email.toLowerCase()])
      identity.set(key, [...(identity.get(key) ?? []), row.id])
      shared.set(email.toLowerCase(), [...(shared.get(email.toLowerCase()) ?? []), row.id])
    }
    departments.forEach((groups, i) => {
      const c = row.cells[i], key = departmentKey(c)
      if (!key) return
      const group = groups.get(key) ?? { values: new Set<string>(), ids: [] }
      group.values.add(c); group.ids.push(row.id); groups.set(key, group)
    })
  }
  for (const ids of exactDuplicates(rows)) duplicateGroups.push({ reason: 'Exact duplicate row (all columns match)', row_ids: ids, safe: true })
  for (const ids of identity.values()) if (ids.length > 1) duplicateGroups.push({ reason: 'Same normalized participant name and email', row_ids: ids, safe: false })
  for (const ids of shared.values()) if (ids.length > 1) duplicateGroups.push({ reason: 'Shared email: may be distinct participants; review before import', row_ids: ids, safe: false })
  departments.forEach((groups, column) => groups.forEach(group => {
    if (group.values.size > 1) group.ids.forEach(id => issues.push({ row_id: id, column, severity: 'warning', problem: 'Inconsistent department naming (case, spacing or abbreviation); choose a value manually', value: '', suggestion: null }))
  }))
  return { issues, duplicateGroups }
}
