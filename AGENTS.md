# AGENTS.md

## Project overview
PanoPro v2 is a rewrite and expansion of an existing pano processing app into a full pano management and review platform.

V1 focused on:
- importing drone panos
- assigning panos to areas
- reviewing panos on a map
- renaming files reliably

V2 must preserve those core workflows while expanding the system into a richer platform for:
- archive organization
- collections
- map-based review
- 360 pano viewing
- pano-to-pano navigation
- notes, issues, and annotations
- tags and filtering
- duplicate review
- exports and reporting
- future web-ready architecture

## Product direction
This repository is evolving from a single-purpose desktop utility into a structured pano operations and review platform.

The intended direction is:
- desktop-first, but web-ready
- modular architecture
- central database for metadata and relationships
- file storage for original panos and generated assets
- clearer separation of UI, business logic, and data handling

Do not treat this project as a simple file renamer. It is becoming a pano management, inspection, and review system.

## Core workflows to preserve
Any changes should respect and preserve the following workflows:

- Import DJI panos
- Spatially classify and assign panos
- Review panos on a map
- Rename panos reliably where required
- Organize panos into archive folders and collections
- Open panos in a 360 viewer
- Navigate between related panos
- Add notes, issues, and annotations
- Tag and filter panos
- Export reports and review outputs

## High-priority product concepts
The following concepts are important and should be preserved during refactors or rewrites:

- archive folders
- collections
- synchronized map / list / viewer behavior
- 360 pano viewer
- hotspots and pano-to-pano navigation
- notes and issue tracking
- annotations
- tags and metadata filtering
- duplicate review
- thumbnails
- bulk review workflows
- report export
- audit history
- weekly auto-collections

Do not remove or weaken these concepts without being explicitly asked.

## Architecture guidance
When making implementation decisions, prefer the following direction:

- Keep the system modular
- Separate frontend, backend, and domain logic cleanly
- Prefer a central metadata database over scattered local state
- Store large binaries in file storage, not directly in the database
- Keep desktop-specific behavior isolated where possible
- Make decisions that improve future web portability

Avoid reinforcing architecture that depends on:
- one giant frontend file
- one giant backend file
- tightly coupled UI and processing logic
- local-only assumptions that block future deployment

## Database guidance
The application database is intended to manage metadata and relationships such as:

- templates
- areas
- overlays
- panos/photos
- collections
- archive folders
- tags
- annotations
- issues
- hotspots
- viewer state
- audit trail
- job state

The database should generally store:
- metadata
- identifiers
- paths
- geometry
- relationships
- status

The database should generally not store:
- large pano image binaries
- generated PDFs
- large thumbnails or derived media blobs unless explicitly justified

## Working style for agents
- Do not commit directly to `main`
- Make focused, reviewable changes
- Prefer small pull requests
- Keep edits limited to files relevant to the task
- Preserve existing working behavior unless explicitly changing it
- Explain assumptions clearly
- Call out risks before making broad structural changes
- Prefer incremental improvements over speculative rewrites

## Refactor rules
Refactors are allowed, but they must support the intended product direction.

Good refactors:
- improving modularity
- isolating business logic
- reducing fragility
- making map/viewer/archive logic easier to maintain
- preparing for central database use
- improving future web readiness

Bad refactors:
- broad rewrites without a clear migration path
- replacing working flows without preserving behavior
- introducing unnecessary frameworks or dependencies
- changing naming, structure, or folder layout without a strong reason
- removing core pano review concepts

## Documentation expectations
When relevant, keep docs aligned with the repo:
- README
- CONTRIBUTING.md
- docs/project-plan.md
- architecture notes if added later

If repeated confusion appears, propose doc updates instead of relying on unstated assumptions.

## Pull request expectations
Each PR should:
- summarize what changed
- explain why it changed
- note any preserved workflows
- call out risks or follow-up work
- mention areas needing human review

## What to avoid
- Do not rewrite the whole project unless explicitly asked
- Do not simplify the product into only a file renaming tool
- Do not remove archive, collection, viewer, annotation, issue, or reporting concepts
- Do not overfit the code to desktop-only assumptions
- Do not introduce complexity without a clear architectural benefit

## Preferred workflow
1. Understand the task in the context of PanoPro v2
2. Preserve core workflows and product direction
3. Make the smallest useful change
4. Keep the diff clean and reviewable
5. Explain what changed and why
