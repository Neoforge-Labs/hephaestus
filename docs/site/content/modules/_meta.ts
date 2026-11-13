import type { MetaRecord } from 'nextra'

// Sidebar order and titles for the per-module guides. Hand-written, not
// generated: tools/gen_site_pages.py manages `reference/_meta.ts` and
// `adrs/_meta.ts` and nothing in this directory, so a page added here is a
// page to list here. An unlisted route is still published, appended
// alphabetically.
//
// Order is editorial, and alphabetical is wrong for the research spine: a
// reader meets a config, captures its provenance, records a run, replays it,
// gates the result and then tracks it, and `lab.gates` sorting between
// `lab.config` and `lab.record` would put the CI gate before the record it
// checks. The money-path module comes first because it is the one a
// production reader is here for.
const meta: MetaRecord = {
  idempotency: 'Idempotency',
  'lab.config': 'lab.config',
  'lab.repro': 'lab.repro',
  'lab.record': 'lab.record',
  'lab.replay': 'lab.replay',
  'lab.gates': 'lab.gates',
  'lab.track': 'lab.track'
}

export default meta
