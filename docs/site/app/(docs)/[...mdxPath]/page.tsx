import { generateStaticParamsFor, importPage } from 'nextra/pages'
import { useMDXComponents as getMDXComponents } from '../../../mdx-components'

/** Every MDX page under content/, rendered in the docs shell.
 *
 * The catch-all is required (`[...mdxPath]`, not `[[...mdxPath]]`) so that `/`
 * belongs to the landing page alone; an optional catch-all also matches `/` and
 * Next.js rejects the duplicate route. Any root-level param the page map still
 * reports is dropped for the same reason.
 */
export async function generateStaticParams() {
  const params = await generateStaticParamsFor('mdxPath')()
  return params.filter((p: { mdxPath?: string[] }) => (p.mdxPath?.length ?? 0) > 0)
}

type Props = { params: Promise<{ mdxPath: string[] }> }

export async function generateMetadata(props: Props) {
  const params = await props.params
  const { metadata } = await importPage(params.mdxPath)
  return metadata
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Wrapper = (getMDXComponents() as any).wrapper

export default async function Page(props: Props) {
  const params = await props.params
  const { default: MDXContent, toc, metadata, sourceCode } = await importPage(params.mdxPath)
  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={sourceCode}>
      <MDXContent {...props} params={params} />
    </Wrapper>
  )
}
