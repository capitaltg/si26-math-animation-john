# PR #38 review follow-up

## Scope

Address the two review findings without changing the approval workflow's
external API or persistence schema.

## Backend approval freshness

`approve_draft_service` will treat a validation report as stale unless its
`compiler_version` and `renderer_version` match the current values from
`app.meta.versions`. This check follows the existing artifact-hash check and
raises `ApprovalPreconditionError`, preserving the endpoint's existing 422
mapping. A focused service test will prove that each stale version blocks
publication.

## Failed-validation recovery in the review panel

`MetaReviewPanel` will request both `pending_review` and `failed_validation`
drafts, merge the returned summaries by id, and retain the existing review
flow. That makes the endpoint's explicitly editable `failed_validation` state
reachable from the UI, where saving a corrected fixture re-runs validation and
can return the draft to `pending_review`. A frontend test will verify that a
failed-validation summary is rendered and can be opened.

## Non-goals

- No change to database migrations, route shapes, or approval request bodies.
- No attempt to edit approved, rejected, or superseded drafts.
- No change to the server's authority over fixture and approval preconditions.
