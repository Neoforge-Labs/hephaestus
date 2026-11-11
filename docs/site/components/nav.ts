/** The site's navigation, in one place.
 *
 * Two shells render it: the landing page's own header and Nextra's Navbar on
 * every docs page. Listing the links twice is how they drift, so both read this.
 * `docs/site/tests/landing.test.ts` asserts the exported hrefs appear in the
 * built root page.
 */
export type NavLink = { href: string; label: string; external?: boolean }

export const NAV_LINKS: NavLink[] = [
  { href: '/docs', label: 'Docs' },
  { href: '/spec', label: 'Spec' },
  { href: '/errors', label: 'Errors' },
  { href: '/reference/modules', label: 'Modules' },
  { href: '/roadmap', label: 'Roadmap' }
]

export const REPO_URL = 'https://github.com/Neoforge-Labs/hephaestus'
