import type { ReactNode } from 'react'
import { Footer, Layout, Navbar } from 'nextra-theme-docs'
import { Head } from 'nextra/components'
import { getPageMap } from 'nextra/page-map'
import 'nextra-theme-docs/style.css'

// The brand files are generated and committed under public/brand (the logo
// design; tools/gen_brand_raster.py). Nothing references them unless the head
// does, so a social preview would be blank with the card sitting right there.
// metadataBase makes the og:image absolute, which crawlers require: the host is
// hephkit.dev by ADR 0019.
export const metadata = {
  metadataBase: new URL('https://hephkit.dev'),
  title: { default: 'Hephaestus', template: '%s | Hephaestus' },
  description: "NeoForge Labs' full-stack kit: the forge every ingot is built from.",
  icons: {
    icon: [{ url: '/brand/favicon.svg', type: 'image/svg+xml' }],
    apple: [{ url: '/brand/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }]
  },
  openGraph: {
    type: 'website',
    siteName: 'Hephaestus',
    url: '/',
    images: [{ url: '/brand/og-card.png', width: 1200, height: 630 }]
  },
  twitter: { card: 'summary_large_image', images: ['/brand/og-card.png'] }
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
