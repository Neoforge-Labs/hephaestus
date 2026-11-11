import type { ReactNode } from 'react'
import { Footer, Layout, Navbar } from 'nextra-theme-docs'
import { getPageMap } from 'nextra/page-map'
import { Mark } from '../../components/Mark'
import { NAV_LINKS, REPO_URL } from '../../components/nav'

/** The docs shell.
 *
 * Its own route group, so the landing page at `/` is not wrapped in sidebar
 * chrome. The link set and the mark come from the same modules the landing page
 * uses, so the two surfaces cannot drift into looking like different sites.
 */
export default async function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <Layout
      navbar={
        <Navbar
          logo={
            <span className="brand">
              <Mark size={24} />
              <span className="brand-word">hephkit</span>
            </span>
          }
          projectLink={REPO_URL}
        >
          {NAV_LINKS.filter(l => l.href !== '/docs').map(l => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
        </Navbar>
      }
      pageMap={await getPageMap()}
      docsRepositoryBase="https://github.com/Neoforge-Labs/hephaestus/tree/main/docs/site"
      editLink="Edit this page"
      footer={
        <Footer>
          <span>
            MIT © NeoForge Labs · Hephaestus is the project, <code>hephkit</code> is how it
            installs.
          </span>
        </Footer>
      }
    >
      {children}
    </Layout>
  )
}
