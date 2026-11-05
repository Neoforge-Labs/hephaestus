import type { ReactNode } from 'react'
import { Footer, Layout, Navbar } from 'nextra-theme-docs'
import { Head } from 'nextra/components'
import { getPageMap } from 'nextra/page-map'
import 'nextra-theme-docs/style.css'

export const metadata = {
  title: { default: 'Hephaestus', template: '%s | Hephaestus' },
  description: "NeoForge Labs' full-stack kit: the forge every ingot is built from."
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head />
      <body>
        <Layout
          navbar={
            <Navbar
              logo={<strong>heph</strong>}
              projectLink="https://github.com/Neoforge-Labs/hephaestus"
            >
              <a href="/">Docs</a>
              <a href="/spec">Spec</a>
              <a href="/adrs">ADRs</a>
              <a href="https://github.com/Neoforge-Labs/hephaestus">GitHub</a>
            </Navbar>
          }
          pageMap={await getPageMap()}
          docsRepositoryBase="https://github.com/Neoforge-Labs/hephaestus/tree/main/docs/site"
          footer={<Footer>MIT © NeoForge Labs</Footer>}
        >
          {children}
        </Layout>
      </body>
    </html>
  )
}
