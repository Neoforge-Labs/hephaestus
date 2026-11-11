/** The hephkit mark and lockup, inline.
 *
 * public/brand/mark.svg and lockup.svg are the drawn source of truth and still
 * ship as files (the favicon and the raster pipeline read them). They are
 * repeated here as components for one reason: an <img> cannot take its colour
 * from the theme, and the mark has to be bronze on ink and bronze-deep on
 * paper -- the swap palette.json requires, because bronze is 2.7:1 on paper.
 * The geometry below is copied verbatim from those files; tests/brand.test.ts
 * fails if the strike path here and the one in mark.svg ever differ.
 */
export const STRIKE_PATH = 'M48 18 L55 41 L78 48 L55 55 L48 78 L41 55 L18 48 L41 41 Z'

export function Mark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 96 96"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="hephkit"
      focusable="false"
    >
      <mask id="mark-strike" maskUnits="userSpaceOnUse" x="0" y="0" width="96" height="96">
        <rect width="96" height="96" fill="#fff" />
        <path d={STRIKE_PATH} fill="#000" />
      </mask>
      <rect x="10" y="10" width="76" height="76" rx="18" fill="currentColor" mask="url(#mark-strike)" />
    </svg>
  )
}

export function Lockup({ className }: { className?: string }) {
  return (
    <span className={className}>
      <Mark size={28} />
      <span>hephkit</span>
    </span>
  )
}
