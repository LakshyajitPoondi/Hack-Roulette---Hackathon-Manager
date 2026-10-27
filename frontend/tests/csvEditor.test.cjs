const { test } = require('node:test')
const assert = require('node:assert/strict')
const { replaceValues, sortRows, deduplicateExact, inspectRows } = require('../../output/csv-editor-tests/services/csvEditor.js')

const headers = ['name', 'email', 'department', 'notes']
const rows = [
  { id: 1, cells: ['John', 'shared@example.com', 'CSE', 'Keep values together'] },
  { id: 2, cells: ['Jonathan', 'shared@example.com', 'CSE-AI', 'Different person'] },
  { id: 3, cells: ['John', 'shared@example.com', 'CSE', 'Keep values together'] },
  { id: 4, cells: ['Alice', 'alice@example.com', 'cse', 'Lowercase'] },
]

test('replacement is whole-cell by default, case-sensitive, column-specific and immutable', () => {
  const original = JSON.stringify(rows)
  const result = replaceValues(rows, 2, 'CSE', 'Computer Science and Engineering')
  assert.deepEqual(result.affected.map(r => r.id), [1, 3])
  assert.equal(result.rows[1].cells[2], 'CSE-AI')
  assert.equal(result.rows[3].cells[2], 'cse')
  assert.deepEqual(result.rows[0].cells.slice(0, 2), rows[0].cells.slice(0, 2))
  assert.equal(JSON.stringify(rows), original)
  assert.deepEqual(replaceValues(rows, 2, 'CSE', 'CS', true).affected.map(r => r.id), [1, 3, 4])
})

test('sorting preserves row IDs, column order and every original value', () => {
  const before = JSON.stringify(rows)
  const ascending = sortRows(rows, 0)
  const descending = sortRows(rows, 0, true)
  assert.deepEqual(ascending.map(r => r.id), [4, 1, 3, 2])
  assert.deepEqual(descending.map(r => r.id), [2, 1, 3, 4])
  for (const row of ascending) assert.deepEqual(row.cells, rows.find(r => r.id === row.id).cells)
  assert.equal(JSON.stringify(rows), before)
})

test('safe dedup removes only identical rows and preserves different shared-email participants', () => {
  const report = inspectRows(headers, rows)
  assert.ok(report.duplicateGroups.some(g => g.safe && JSON.stringify(g.row_ids) === '[1,3]'))
  assert.ok(report.duplicateGroups.some(g => g.reason.startsWith('Shared email') && g.row_ids.length === 3))
  assert.deepEqual(deduplicateExact(rows).map(r => r.id), [1, 2, 4])
  assert.equal(rows.length, 4)
})

test('validation updates immediately after correcting a cell without guessing missing data', () => {
  const invalid = [{ id: 1, cells: [' Rahul ', 'rahul @gmail.com', 'CSE', ''] },
    { id: 2, cells: ['', '', 'cse', ''] }, { id: 3, cells: ['', '', '', ''] }]
  const report = inspectRows(headers, invalid)
  assert.ok(report.issues.some(i => i.row_id === 1 && i.suggestion === 'rahul@gmail.com'))
  assert.ok(report.issues.some(i => i.problem.includes('department')))
  assert.ok(report.issues.some(i => i.row_id === 2 && i.problem === 'Missing required email' && i.suggestion === null))
  assert.ok(report.issues.some(i => i.row_id === 3 && i.problem === 'Empty row'))
  const fixed = replaceValues(invalid, 1, 'rahul @gmail.com', 'rahul@gmail.com').rows
  assert.ok(!inspectRows(headers, fixed).issues.some(i => i.row_id === 1 && i.problem === 'Invalid email format'))
  const departmentVariants = inspectRows(headers, [rows[0], { id: 5, cells: ['Other', 'other@example.com', 'Computer Science and Engineering', ''] }])
  assert.ok(departmentVariants.issues.some(i => i.row_id === 5 && i.problem.includes('abbreviation') && i.suggestion === null))
})

test('5000-row edits preserve stable IDs and the previous array can be restored by undo', () => {
  const large = Array.from({ length: 5000 }, (_, i) => ({ id: i + 1, cells: [`Person ${i}`, `p${i}@example.com`, i % 2 ? 'CSE-AI' : 'CSE', String(i)] }))
  const history = [large]
  const changed = replaceValues(large, 2, 'CSE', 'Computer Science').rows
  assert.equal(changed.filter(r => r.cells[2] === 'Computer Science').length, 2500)
  assert.equal(sortRows(changed, 3, true)[0].id, 5000)
  assert.equal(inspectRows(headers, changed).issues.length, 0)
  assert.equal(history.at(-1)[0].cells[2], 'CSE')
})
