type Budget = {
  bootSeconds: number
  bootWhat: string
  wheelMb: number
  wheelTarget: string
}

/** The two numbers the five-minute promise rests on.
 *
 * Read from tools/dx_budget.json by way of the generated snippet, never typed
 * here. They are ceilings a scheduled CI run enforces with
 * `tools/dx_budget.sh --enforce`, not a best-case measurement: the page claims
 * what is held, so raising the budget moves the page and nothing else has to be
 * remembered.
 *
 * Rendered as rows rather than as big-number tiles on purpose. Two figures do
 * not carry a metric wall, and the page already speaks in rows on hairlines.
 */
export function BudgetTiles({ budget }: { budget: Budget }) {
  const rows = [
    {
      figure: `${budget.bootSeconds}s`,
      label: 'Local stack up, start to healthy',
      note: `${budget.bootWhat}.`
    },
    {
      figure: `${budget.wheelMb} MB`,
      label: 'The wheel an install pulls down',
      note: `${budget.wheelTarget}, measured on the published artifact, not a local build.`
    }
  ]

  return (
    <dl className="budget">
      {rows.map(row => (
        <div key={row.label} className="budget-row">
          <dt>
            <span className="budget-cap">under</span>
            <span className="budget-figure">{row.figure}</span>
          </dt>
          <dd>
            <strong>{row.label}</strong>
            <span>{row.note}</span>
          </dd>
        </div>
      ))}
      <p className="budget-rule">
        Both are enforced, not aspirational: <code>tools/dx_budget.sh --enforce</code> fails the
        scheduled build when either is breached. They are ceilings — the figure a run reports is
        usually well under them.
      </p>
    </dl>
  )
}
