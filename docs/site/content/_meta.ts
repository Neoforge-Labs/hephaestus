import type { MetaRecord } from 'nextra'

// Sidebar order and titles. Unlisted routes are appended alphabetically.
// Hand-written on purpose: order is editorial. What the project is, then the
// contract (spec, errors), then reference, then the why (ADRs) and the plan.
const meta: MetaRecord = {
  index: 'Overview',
  spec: 'Specification',
  errors: 'Error codes',
  reference: 'Reference',
  adrs: 'Decisions',
  roadmap: 'Roadmap'
}

export default meta
