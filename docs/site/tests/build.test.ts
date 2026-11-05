import { expect, test } from 'bun:test'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const out = join(import.meta.dir, '..', 'out')

test('test_static_export_includes_search_index', () => {
  const index = join(out, 'index.html')
  expect(existsSync(index)).toBe(true)
  expect(readFileSync(index, 'utf8')).toContain('heph')
  expect(existsSync(join(out, '_pagefind', 'pagefind.js'))).toBe(true)
  expect(existsSync(join(out, 'errors'))).toBe(false)
})
