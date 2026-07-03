# PanoPro Project Plan

## Product summary
PanoPro is a project focused on organizing, managing, and improving panoramic or site-visualization workflows in a cleaner and more usable system.

## Branding and identity
- The product name is PANO PRO for prominent UI or installer-facing titles.
- Use PanoPro in normal prose and developer-facing documentation.
- Legacy Joe-based product names are incorrect branding and should not be reintroduced.
- Keep internal technical identifiers such as `pano_namer`, `.pano_namer_data`, `pano_namer.db`, and `PANOPRO_AUTH_*` stable unless there is an explicit migration plan.

## MVP goal
Create a simple first version that proves the core workflow and gives a clear foundation for future development.

## In scope for MVP
- Basic project structure
- Clear documentation
- Defined collaboration workflow
- Initial feature planning
- Review and cleanup of current repository structure

## Out of scope for MVP
- Full production deployment
- Advanced automation
- Complex user management
- Large-scale refactors without a plan

## Immediate next tasks
1. Review current folder structure
2. Review and improve existing README if needed
3. Define exact MVP features
4. Identify first build priorities
5. Create and track feature tasks in GitHub Projects

## Collaboration workflow
- Track tasks in the GitHub Project board
- Use feature branches for all work
- Merge changes through pull requests only

## Backend architecture planning
- See `docs/backend-multi-user-audit.md` for the current database/import/rename audit and the staged plan for SQLite migration discipline, batch-aware rename reservations, organization/user scaffolding, Postgres compatibility, and eventual production Postgres migration.

