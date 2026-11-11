import Link from 'next/link'
import { CopyCommand } from '../components/CopyCommand'
import { Mark } from '../components/Mark'
import { ModuleLedger } from '../components/ModuleLedger'
import { RoadmapStrip } from '../components/RoadmapStrip'
import { NAV_LINKS, REPO_URL } from '../components/nav'
import data from '../content/_snippets/site-data.json'
import './landing.css'

export const metadata = {
  title: 'Hephaestus — stop setting up, start building',
  description:
    'A full-stack kit with one correctness core: money in integer minor units, canonical JSON, signed webhooks, registry-backed errors, and a local stack that boots with one command.'
}

export default function Landing() {
  const install = 'uv add hephkit'

  return (
    <div className="landing">
      <header className="site-head">
        <Link href="/" className="brand" aria-label="hephkit home">
          <Mark size={26} />
          <span className="brand-word">hephkit</span>
        </Link>
        <nav className="site-nav" aria-label="Main">
          {NAV_LINKS.map(l => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
          <a href={REPO_URL} className="site-nav-repo">
            GitHub
          </a>
        </nav>
      </header>

      <main>
        <section className="hero">
          <div className="hero-plate" aria-hidden="true">
            <Mark size={340} />
          </div>
          <h1 className="hero-line">
            Stop setting up.
            <br />
            Start building.
          </h1>
          <p className="hero-sub">
            Hephaestus is the kit every NeoForge project is built from: one correctness core for
            money, hashing, signatures and errors, and a local stack that comes up with one command.
            You write the part that is actually yours.
          </p>

          <CopyCommand command={install} hint="Python 3.12+. The CLI is a separate install." />

          <p className="hero-meta">
            <code>hephkit</code> <a href="https://pypi.org/project/hephkit/">on PyPI</a> · spec{' '}
            <Link href="/spec">v{data.specVersion}</Link> · MIT ·{' '}
            <span className="hero-maturity">every module experimental</span>
          </p>
        </section>

        <section className="band">
          <h2 className="band-h">What you get instead of a week of setup</h2>
          <dl className="claims">
            <div className="claim">
              <dt>Money that cannot quietly lose a cent</dt>
              <dd>
                Integer minor units end to end, strict ASCII parsing that refuses excess precision,
                and the full ISO 4217 table generated from its published source. Floating point
                never touches an amount. Pinned by{' '}
                <Link href="/spec">the specification</Link> and shared conformance vectors, not by
                one language&rsquo;s tests.
              </dd>
            </div>
            <div className="claim">
              <dt>Errors with an address</dt>
              <dd>
                Every failure carries a code from one registry and a{' '}
                <code>type</code> URL that resolves to a page explaining it —{' '}
                {data.errorCodeCount} of them,{' '}
                <Link href="/errors">all documented</Link>. The wire format is a MUST in the spec,
                so a client can rely on it across every language in the kit.
              </dd>
            </div>
            <div className="claim">
              <dt>One core, bound everywhere</dt>
              <dd>
                The hard parts live once, in Rust that does no I/O and never panics on input. Python
                binds to it, Go calls it, and nothing is hand-ported between languages — so the
                three cannot disagree about what a rounded split or a canonical hash is.
              </dd>
            </div>
            <div className="claim">
              <dt>A local stack, not a wiki page of prerequisites</dt>
              <dd>
                Postgres, Redis, object storage, mail and the full telemetry pipeline are Compose
                fragments you switch on per project. Traces, metrics and logs are already wired to
                the same conventions.
              </dd>
            </div>
          </dl>
        </section>

        <section className="band band-ledger">
          <h2 className="band-h">What is actually built</h2>
          <p className="band-sub">
            The kit is in Phase {data.currentPhase} of seven. This is the whole inventory, read from
            the registry the code is checked against — not a highlight reel.
          </p>
          <ModuleLedger shipped={data.shipped} planned={data.planned} />
        </section>

        <section className="band">
          <h2 className="band-h">Where it is going</h2>
          <RoadmapStrip phases={data.phases} current={data.currentPhase} />
        </section>

        <section className="band band-start">
          <h2 className="band-h">Start</h2>
          <div className="starts">
            <CopyCommand command={install} />
            <CopyCommand
              command="go install github.com/Neoforge-Labs/hephaestus/go/cmd/heph@latest"
              hint="The heph CLI, for the local stack."
            />
          </div>
          <p className="starts-next">
            Then read <Link href="/docs">the docs</Link>, or go straight to{' '}
            <Link href="/spec">the specification</Link> if you would rather see the contract before
            the prose.
          </p>
        </section>
      </main>

      <footer className="site-foot">
        <div className="foot-brand">
          <Mark size={22} />
          <span>hephkit</span>
        </div>
        <nav className="foot-nav" aria-label="Footer">
          {NAV_LINKS.map(l => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
          <Link href="/adrs">Decisions</Link>
          <a href={REPO_URL}>GitHub</a>
          <a href="https://pypi.org/project/hephkit/">PyPI</a>
        </nav>
        <p className="foot-fine">
          MIT © NeoForge Labs · spec v{data.specVersion} · Hephaestus is the project,{' '}
          <code>hephkit</code> is how it installs.
        </p>
      </footer>
    </div>
  )
}
