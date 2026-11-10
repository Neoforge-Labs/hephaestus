<!-- The checks run in CI. These are the questions a check cannot answer. -->

## What and why

## Does the spec change in this PR?

Behaviour is defined in `spec/heph-spec.md` and pinned by `conformance/` vectors
first. If this changes behaviour, the spec and the vectors change here too, plus
an ADR if a decision changed.

- [ ] No behaviour changes
- [ ] Spec and vectors are updated in this PR (ADR: )

## Where did any new vector come from?

Vectors come from independent sources: an RFC, a reference package
(`standardwebhooks`, `rfc8785`) or a hand derivation. Never from running our own
implementation, and never "fixed" by it.

- [ ] No new or changed vectors
- [ ] Source of each new or changed vector, named here:

## Does the maturity label still hold?

Every module is `experimental`, `beta` or `stable`, and new work starts
`experimental`. Nothing in a production money path may be below `stable`.

- [ ] No module's label changes, and none of it newly sits in a money path
- [ ] A label changes, and the criteria in the design are met (say how):
