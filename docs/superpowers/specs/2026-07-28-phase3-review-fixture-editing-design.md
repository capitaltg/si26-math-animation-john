# Phase 3 Reviewer Fixture Editing Design

## Goal

Close the Phase 3 review gaps: a reviewer can correct a fixture's params and
record an expected result, but the server accepts the edit only when the params
pass the draft's schema and guard and the expected result agrees with the
draft's compiled answer expression.

## API

Extend `POST /meta/drafts/{draft_id}/fixtures/{fixture_id}` to accept:

```json
{"params": {"n": 5}, "expected_result": {"answer": "5"}}
```

The endpoint loads the fixture and draft, compiles the persisted params,
guard, and answer-expression documents, validates `params`, evaluates the
compiled answer expression, and requires `expected_result.answer` to be the
same canonical numeric value. On validation or mismatch it returns HTTP 422
without changing the fixture. On success it persists both JSON fields and
returns the updated fixture.

This endpoint remains dev-only because its router is mounted only while
`meta_templates_enabled` is set. It does not approve, publish, or re-run a
draft.

## UI

The selected-draft fixture list exposes editable JSON textareas for `params`
and `expected_result`, plus a per-fixture save action. Server validation errors
are displayed in the panel. The existing reject-with-feedback workflow remains
unchanged.

## Tests

- API: successful params/result update; invalid params rejected without a
  write; mismatched expected result rejected without a write.
- UI: edit a fixture and verify the correct request payload; show a rejected
  save error.
- Existing meta/render and focused frontend suites remain green.

## Scope

This change does not add approval, template publication, dynamic classifier
integration, or a new DSL node. It uses Phase 2's existing compiled params and
expression implementations.
