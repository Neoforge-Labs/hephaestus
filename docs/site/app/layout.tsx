import type { ReactNode } from 'react'
import { IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google'
import { Head } from 'nextra/components'
// Order matters and is the reason both stylesheets are imported here rather
// than in the docs layout: Next.js emits CSS in import order, and the root
// layout's imports precede a child layout's. Nextra's base first, our tokens
// second, so ours win.
import 'nextra-theme-docs/style.css'
import './global.css'

// Self-hosted at build time by next/font, so no runtime request to Google and
// no layout shift. Plex is the industrial lineage the mark belongs to, and its
// mono is the voice for the thing this site is mostly about: commands.
const sans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap'
})

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
  display: 'swap'
})

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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      dir="ltr"
      className={`${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <Head color={{ hue: 31, saturation: 50, lightness: 52 }} backgroundColor={{ dark: '#0c0a09', light: '#f5f0e8' }} />
      <body>{children}</body>
    </html>
  )
}
