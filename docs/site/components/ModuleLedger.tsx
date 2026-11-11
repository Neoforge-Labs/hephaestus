import Link from 'next/link'

type Shipped = { name: string; home: string; maturity: string }
type Planned = { name: string; home: string; phase: number }

const HOME_LABEL: Record<string, string> = {
  python: 'Python',
  rust: 'Rust',
  go: 'Go',
  compose: 'Compose',
  docker: 'Images',
  ts: 'TypeScript'
}

function homeLabel(home: string) {
  return HOME_LABEL[home] ?? home
}

/** What runs today, and what does not, from spec/modules.yaml.
 *
 * Both sides come from the same registry, so the page cannot advertise a module
 * that is not there or quietly keep claiming one that moved. The maturity shown
 * is the registry's, which tools/check_modules.py holds equal to the label in
 * the module's own source.
 */
export function ModuleLedger({ shipped, planned }: { shipped: Shipped[]; planned: Planned[] }) {
  const byHome = new Map<string, Shipped[]>()
  for (const m of shipped) {
    const list = byHome.get(m.home) ?? []
    list.push(m)
    byHome.set(m.home, list)
  }
  const byPhase = new Map<number, Planned[]>()
  for (const m of planned) {
    const list = byPhase.get(m.phase) ?? []
    list.push(m)
    byPhase.set(m.phase, list)
  }

  return (
    <div className="ledger">
      <div className="ledger-side">
        <h3 className="ledger-head">
          Runs today
          <span className="ledger-count">{shipped.length}</span>
        </h3>
        <dl className="ledger-list">
          {[...byHome.entries()].map(([home, mods]) => (
            <div key={home} className="ledger-row">
              <dt>{homeLabel(home)}</dt>
              <dd>
                {mods.map(m => (
                  <code key={m.name} className="chip chip-on">
                    {m.name}
                  </code>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="ledger-side">
        <h3 className="ledger-head ledger-head-muted">
          Not yet
          <span className="ledger-count">{planned.length}</span>
        </h3>
        <dl className="ledger-list">
          {[...byPhase.entries()].map(([phase, mods]) => (
            <div key={phase} className="ledger-row">
              <dt>Phase {phase}</dt>
              <dd>
                {mods.map(m => (
                  <code key={m.name} className="chip">
                    {m.name}
                  </code>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <p className="ledger-rule">
        Every module above is <code>experimental</code>: usable, not yet promised. Nothing reaches{' '}
        <code>stable</code> without the coverage gate, two production projects and passing ecosystem
        CI — the criteria in <Link href="/adrs/0015-maturity-levels">ADR 0015</Link>. The planned
        column lists the headline modules per phase, not the full scope; the{' '}
        <Link href="/roadmap">roadmap</Link> has that.
      </p>
    </div>
  )
}
