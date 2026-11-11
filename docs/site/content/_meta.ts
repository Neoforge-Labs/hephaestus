import type { MetaRecord } from 'nextra'

// Sidebar order and titles. Unlisted routes are appended alphabetically.
// Hand-written on purpose: order is editorial. What the project is, then the
// contract (spec, errors), then reference, then the why (ADRs) and the plan.
//
// There is no `index` row: `/` is the landing page (app/page.tsx), outside this
// content tree, and the docs overview lives at `/docs`.
const meta: MetaRecord = {
  // The landing page is an app route, so Nextra's page map still sees `/` and
  // would list it in the docs sidebar under its marketing title. It is not a
  // docs page; the mark in the navbar is the way back to it.
  index: { display: 'hidden' },
  docs: 'Overview',
  spec: 'Specification',
  errors: 'Error codes',
  reference: 'Reference',
  adrs: 'Decisions',
  roadmap: 'Roadmap'
}

export default meta
