import { expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { NAV_LINKS, REPO_URL } from '../components/nav'
import { STRIKE_PATH } from '../components/Mark'
import data from '../content/_snippets/site-data.json'

const site = join(import.meta.dir, '..')
const out = join(site, 'out')
const raw = readFileSync(join(out, 'index.html'), 'utf8')

/** The exported page as a reader receives it.
 *
 * Two things in the raw file would otherwise make these assertions lie. Next
 * inlines its flight payload in <script> tags, so every string on the page also
 * appears there and a "this occurs exactly once" check can never pass. And JSX
 * emits `<!-- -->` between an expression and the text beside it, so `12 of
 * them` is really `12<!-- --> of them` in the markup. Both are stripped; what
 * is left is what the browser shows.
 */
const landing = raw.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<!--[\s\S]*?-->/g, '')

/** The landing page's claims are generated, so the tests compare it against the
 *  generated source rather than against hard-coded expectations. A page that
 *  disagrees with spec/modules.yaml fails here, and so does one that quietly
 *  stops rendering a section. */

test('test_every_nav_link_is_on_the_page', () => {
  for (const link of NAV_LINKS) {
    expect(landing).toContain(`href="${link.href}"`)
  }
  expect(landing).toContain(REPO_URL)
})

test('test_ledger_shows_both_sides_from_the_registry', () => {
  // A shipped module and a planned one, each with the side it belongs to.
  expect(data.shipped.length).toBeGreaterThan(0)
  expect(data.planned.length).toBeGreaterThan(0)
  for (const m of data.shipped) expect(landing).toContain(`>${m.name}</code>`)
  for (const m of data.planned) expect(landing).toContain(`>${m.name}</code>`)
  expect(landing).toContain('Runs today')
  expect(landing).toContain('Not yet')
  // The counts are rendered, so a dropped module cannot pass unnoticed.
  expect(landing).toContain(`>${data.shipped.length}</span>`)
  expect(landing).toContain(`>${data.planned.length}</span>`)
})

test('test_maturity_is_stated_and_sourced', () => {
  // Every module is experimental (ADR 0015). The page must say so rather than
  // let a reader assume otherwise, and must cite where the rule lives.
  expect(landing).toContain('experimental')
  expect(landing).toContain('/adrs/0015-maturity-levels')
  for (const m of data.shipped) expect(m.maturity).toBe('experimental')
})

test('test_page_does_not_claim_heph_new', () => {
  // `heph new` is phase 5 and does not exist. It may appear only as a planned
  // module name, never as something the page tells you to run.
  expect(data.planned.some(m => m.name === 'heph new')).toBe(true)
  const occurrences = landing.split('heph new').length - 1
  expect(occurrences).toBe(1)
})

test('test_no_private_product_names', () => {
  for (const name of ['Collie', 'Domus', 'SAWA', 'NeoRx']) {
    expect(landing).not.toContain(name)
  }
})

test('test_install_command_carries_no_version_claim', () => {
  // `uv add hephkit`, unpinned: a pinned version on the front page goes stale
  // the next release and turns the hero into a lie. The release is verified
  // separately; the page states no version it would have to chase.
  expect(landing).toContain('uv add hephkit')
  expect(landing).not.toMatch(/uv add hephkit==/)
})

test('test_phase_marker_matches_the_derived_phase', () => {
  expect(landing).toContain('you are here')
  expect(landing).toContain(`Phase ${data.currentPhase} of seven`)
  // The phase is derived from the earliest planned phase, not declared.
  const earliestPlanned = Math.min(...data.planned.map(m => m.phase))
  expect(data.currentPhase).toBe(earliestPlanned - 1)
})

test('test_error_count_matches_the_registry', () => {
  expect(landing).toContain(`${data.errorCodeCount} of them`)
})

test('test_inline_mark_matches_the_drawn_svg', () => {
  // components/Mark.tsx repeats the geometry of public/brand/mark.svg so the
  // mark can take its colour from the theme. That duplication is the risk: if
  // the drawn file is redesigned and the component is not, the site ships a
  // stale logo. Compare the one part that carries the identity.
  const drawn = readFileSync(join(site, 'public/brand/mark.svg'), 'utf8')
  expect(drawn).toContain(STRIKE_PATH)
})
