type Phase = { phase: number; title: string }

/** The seven phases, with the one in progress marked.
 *
 * `current` is derived in tools/gen_site_pages.py from the earliest planned
 * phase in spec/modules.yaml, so it advances when modules ship rather than when
 * someone remembers to edit a number here.
 */
export function RoadmapStrip({ phases, current }: { phases: Phase[]; current: number }) {
  return (
    <ol className="phases">
      {phases.map(p => {
        const state = p.phase === current ? 'now' : p.phase < current ? 'done' : 'ahead'
        return (
          <li key={p.phase} className={`phase phase-${state}`}>
            <span className="phase-n">{p.phase}</span>
            <span className="phase-t">{p.title}</span>
            {state === 'now' ? <span className="phase-here">you are here</span> : null}
          </li>
        )
      })}
    </ol>
  )
}
