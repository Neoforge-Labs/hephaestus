# 0018. Disambiguate the name "Atlas" across ADRs 0013 and 0014

## Status

Accepted. Date: 2026-11-05. Clarifies the bare name `Atlas` in ADR 0013 and ADR 0014 without reversing either decision; neither of those ADRs is edited.

## Context

Two accepted ADRs use the bare word "Atlas" for two unrelated products.

ADR 0013 lists `Atlas` among the supported vector stores, alongside pgvector, Qdrant, LanceDB and Pinecone. ADR 0014 lists `Atlas` as the adopted tool for relational migrations across every language. Those are different companies' products with no relationship beyond the name, and in a repository whose ADR trail is meant to be the record of why things are the way they are, a reader who meets the word in one ADR and then the other has no way to know they are not the same thing. The migrations choice is the more dangerous half: someone implementing it could reasonably reach for the vector store's tooling, or conclude the two ADRs contradict each other.

ADRs are never edited after acceptance (ADR 0001, and the template says so), so the fix cannot be a word changed in either file. A superseding ADR is the wrong instrument too, because neither decision is being reversed: the vector store stays supported and the migrations tool stays adopted. What is needed is a note the ADR trail carries alongside both, which is what this ADR is.

## Decision

The two names are recorded here, and the fully qualified name is used everywhere from now on.

- In ADR 0013, `Atlas` means **MongoDB Atlas Vector Search** — the vector-search feature of MongoDB's managed service, one of the optional adapters behind the vector port. It is not a default; pgvector is.
- In ADR 0014, `Atlas` means **Atlas by Ariga** (`atlasgo.io`), the declarative schema-migration tool. It is the adopted migrations tool for every language in the monorepo.

Prose, spec text, ADRs, code comments and commit messages write the qualified name — "MongoDB Atlas Vector Search" or "Atlas by Ariga" — on first use in any document, and never the bare word where both are in scope. Where only one is plausibly in scope, such as a migrations runbook, the bare word is acceptable after a qualified first use in that document.

## Consequences

A reader of either ADR can now establish which product is meant, which they could not before. Whoever implements the migrations capability inherits the right tool, and the vector-port adapter list stops looking like it includes a migrations tool.

Nothing in either decision changes, so no code, spec section or configuration moves. ADRs 0013 and 0014 keep their text exactly as accepted; this ADR is the note that has to be read with them, which is a real cost — a reader who finds 0013 or 0014 on their own is not pointed here. That cost is accepted because it is smaller than either editing an accepted ADR or superseding a decision nobody wants changed.

The naming rule also applies to a product name that is merely *likely* to collide, not only to the two above. Naming a tool by a bare word that another adopted tool shares is how this arose, and the cheapest moment to catch the next one is while the ADR is still a draft.
