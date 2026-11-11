import Link from 'next/link'

/** The five-minute path, printed from the script CI runs.
 *
 * The commands are not written here. tools/gen_quickstart.py extracts them from
 * examples/hello/tutorial_test.sh into _snippets/quickstart.json, and `--check`
 * fails if the two disagree -- so a command on the front page is a command that
 * passed in CI, including the one that reads the trace back out of Tempo.
 */
export function ProofBlock({ commands }: { commands: string[] }) {
  return (
    <div className="proof">
      <ol className="proof-steps">
        {commands.map(command => (
          <li key={command}>
            <code>
              <span className="proof-prompt" aria-hidden="true">
                $
              </span>
              {command}
            </code>
          </li>
        ))}
      </ol>
      <p className="proof-note">
        Not an illustration: these are the lines{' '}
        <Link href="/tutorial/first-five-minutes">the tutorial</Link> runs, extracted from the
        script CI executes on every change. The last one answers{' '}
        <code>{'{"price": {"amount": "1020", "currency": "KES"}}'}</code>, and by then the request
        is already a trace in Grafana — there is no tracing code in the example.
      </p>
    </div>
  )
}
