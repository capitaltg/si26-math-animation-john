# Clean Code Refactor Design

## Goal

Improve readability and maintainability across production code, tests, and scripts without changing observable application behavior.

## Scope

The cleanup covers Python code under `backend/`, React and JavaScript code under `frontend/`, Python utilities under `eval/`, and repository scripts under `scripts/`. Configuration and documentation may be adjusted only when needed to support or explain the cleanup.

Public HTTP contracts, persisted data formats, template behavior, rendered output, user-facing copy, and command-line interfaces remain unchanged. Dependencies will not be added solely to support stylistic preferences.

## Approach

Use a balanced, evidence-driven refactor:

- Improve unclear names, duplicated logic, excessive nesting, long functions, and mixed responsibilities.
- Extract focused helpers when the resulting boundary has a clear purpose and is independently understandable.
- Split an oversized file only when the split creates a stable responsibility boundary and existing tests provide strong behavioral coverage.
- Preserve established project conventions unless a local convention actively obscures intent.
- Keep changes reviewable and avoid repository-wide cosmetic churn.

## Comment Policy

Remove comments that paraphrase the adjacent code, label obvious steps, preserve obsolete history, or compensate for unclear naming. Prefer clearer code over explanatory narration.

Keep comments and docstrings that explain information the code cannot express directly, including:

- security, concurrency, persistence, or compatibility constraints;
- non-obvious mathematical or rendering invariants;
- external service behavior and framework ordering requirements;
- intentional deviations from an apparently simpler implementation;
- public interfaces whose documentation is useful to callers.

When a necessary comment is verbose, rewrite it to state the reason or invariant concisely.

## Execution Strategy

Begin with automated and structural inspection to identify high-value cleanup candidates. Prioritize production modules with clear maintainability problems and dependable tests, then apply the same standards to nearby tests and scripts. Each refactor should be behavior-preserving and narrow enough to verify independently.

Large files are candidates, not automatic targets. A file will be split only when responsibility boundaries are clear, imports can remain coherent, and the change does not expose new public APIs unnecessarily.

## Testing and Verification

Use existing tests as characterization coverage. Add or adjust tests only where a refactor exposes an untested behavioral boundary; test changes must preserve existing expectations rather than redefine behavior.

Verification will include:

- the complete default backend pytest suite;
- the complete frontend Vitest suite;
- the production frontend build;
- focused checks for any scripts or modules changed outside those suites;
- a final diff review for accidental API, copy, configuration, or behavioral changes;
- a final comment review to ensure removed comments were redundant and retained comments explain intent.

Browser end-to-end tests and rendering-dependent tests will be run when the affected code or available environment makes them relevant. If an external dependency prevents a relevant check, the limitation and the exact unrun command will be reported.

## Success Criteria

- Production code, tests, and scripts within scope are cleaner without deliberate feature changes.
- Refactored units have clearer names, responsibilities, and control flow.
- Unnecessary comments are removed; retained comments explain rationale or constraints.
- Existing public contracts and user-visible behavior remain intact.
- Required verification passes, or any environment-bound limitation is reported precisely.
