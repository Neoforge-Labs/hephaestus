import nextra from 'nextra'

const withNextra = nextra({})

export default withNextra({
  output: 'export',
  // Mandatory for a static export: the default image optimizer needs a server.
  images: { unoptimized: true }
})
