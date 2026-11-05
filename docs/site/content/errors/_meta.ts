import type { MetaRecord } from 'nextra'

// Sidebar order of the generated error pages: registry order (spec/errors.yaml).
// Hand-written; tools/tests/test_gen_error_pages.py pins these keys to the registry.
const meta: MetaRecord = {
  'HEPH-GEN-500': 'HEPH-GEN-500',
  'HEPH-VAL-422': 'HEPH-VAL-422',
  'HEPH-NF-404': 'HEPH-NF-404',
  'HEPH-AUTH-401': 'HEPH-AUTH-401',
  'HEPH-AUTH-403': 'HEPH-AUTH-403',
  'HEPH-RATE-429': 'HEPH-RATE-429',
  'HEPH-IDEMP-400': 'HEPH-IDEMP-400',
  'HEPH-IDEMP-409': 'HEPH-IDEMP-409',
  'HEPH-IDEMP-422': 'HEPH-IDEMP-422',
  'HEPH-MONEY-422': 'HEPH-MONEY-422',
  'HEPH-MONEY-409': 'HEPH-MONEY-409',
  'HEPH-WH-401': 'HEPH-WH-401'
}

export default meta
