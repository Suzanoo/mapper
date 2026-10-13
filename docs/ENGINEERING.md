# Engineering workflow

## Responsibilities and authority

- Product Owner: requirements, scope authorization and acceptance decisions.
- Coordinator: coordination, acceptance tracking, package review and authorized Git operations.
- Work: technical investigation, implementation, testing and complete delivery; **no Git operations or repository administration**.

Read root README, mapping index, current status, contracts, current authorization, then relevant implementation and tests. Accepted reports are evidence and engineering input; current PO decisions override earlier proposals. Multiple activities per element is required. Never silently replace an existing relationship.

## Change discipline

Implement only authorized milestones. Preserve valid work and renderer independence. Keep presentation changes out of persistence and identity contracts. Any necessary format change requires documented compatibility and migration design; do not silently rewrite an unknown format. Escalate material product conflicts; resolve ordinary engineering choices independently.

Use focused pure-data tests plus boundary mocks for Revit interactions. Mocks, syntax checks and schema validation are not desktop acceptance. Record exact commands, results, environment and skipped coverage. Desktop checks target new risks rather than repeating accepted MS-0 campaigns.

## Delivery and acceptance

Provide complete changed files at repository-relative paths, an overlay ZIP, SHA-256 manifest, concise report, actual automated evidence and a short desktop checklist. Identify the baseline and distinguish implemented/tested, desktop-pending, investigation and proposed work. Preserve historical evidence without retroactively changing its results.

Coordinator reviews and integrates after applicable acceptance gates. PO records desktop outcomes and acceptance. A roadmap is not authorization. Stop after the authorized delivery.
