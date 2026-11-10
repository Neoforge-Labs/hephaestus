import { expect, test } from 'bun:test'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const site = join(import.meta.dir, '..')
const out = join(site, 'out')

/** Newest modification time (ms) of any file under `dir`, with its path. */
function newest(dir: string): { path: string; mtime: number } {
  let best = { path: dir, mtime: 0 }
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    const found = entry.isDirectory() ? newest(path) : { path, mtime: statSync(path).mtimeMs }
    if (found.mtime > best.mtime) best = found
  }
  return best
}

test('test_static_export_includes_search_index', () => {
  const index = join(out, 'index.html')
  expect(existsSync(index)).toBe(true)
  expect(readFileSync(index, 'utf8')).toContain('heph')
  expect(existsSync(join(out, '_pagefind', 'pagefind.js'))).toBe(true)
  // The scaffold asserted errors/ was absent; the error pages are generated content now.
  expect(existsSync(join(out, 'errors.html'))).toBe(true)
  expect(existsSync(join(out, 'errors', 'HEPH-IDEMP-409.html'))).toBe(true)
})

test('test_search_index_has_indexed_pages', () => {
  const entry = join(out, '_pagefind', 'pagefind-entry.json')
  expect(existsSync(entry)).toBe(true)
  const languages = JSON.parse(readFileSync(entry, 'utf8')).languages as Record<string, { page_count: number }>
  const pages = Object.values(languages).reduce((sum, lang) => sum + lang.page_count, 0)
  expect(pages).toBeGreaterThan(0)
})

test('test_exported_head_wires_the_brand_assets', () => {
  // The brand files existing is not the same as the site using them. The
  // missing favicon was found by running the dev server, never by a test;
  // this is that gap closed, asserted on the exported HTML a browser gets.
  const html = readFileSync(join(out, 'index.html'), 'utf8')
  expect(html).toContain('/brand/favicon.svg')
  expect(html).toContain('/brand/apple-touch-icon.png')
  expect(html).toContain('https://hephkit.dev/brand/og-card.png')
  for (const asset of ['favicon.svg', 'apple-touch-icon.png', 'og-card.png']) {
    expect(existsSync(join(out, 'brand', asset))).toBe(true)
  }
})

test('test_static_export_is_not_older_than_its_sources', () => {
  const built = statSync(join(out, 'index.html')).mtimeMs
  for (const dir of ['content', 'app', 'public']) {
    const latest = newest(join(site, dir))
    // A source newer than the export means out/ is stale: rebuild before testing.
    expect(`${latest.path} ${latest.mtime > built ? 'is newer than out/index.html' : 'is not newer'}`).toBe(
      `${latest.path} is not newer`,
    )
  }
})
