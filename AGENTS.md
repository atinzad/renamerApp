# Repository Guidelines

## Project Structure & Module Organization
The repository is currently empty. As code is added, keep the layout predictable:
- `src/` for application code.
- `tests/` for automated tests.
- `assets/` for static files (images, fixtures, sample data).

If you introduce new top-level folders, document them here with a short purpose line.

## Build, Test, and Development Commands
No build or test tooling is configured yet. Once added, list the exact commands, for example:
- `npm run dev` — start the local dev server.
- `npm test` — run the test suite.

Keep this section updated as soon as you add a package manager or scripts.

## Coding Style & Naming Conventions
No formatter or linter is configured. Until tooling is added:
- Use 2-space indentation for JSON/JS, 4-space for Python.
- Use `kebab-case` for filenames and `PascalCase` for classes/types.
- Prefer descriptive names over abbreviations.

If you adopt a formatter (e.g., Prettier, Black), add the exact command here.

## Testing Guidelines
Testing framework is not set up yet. When you add tests:
- Place unit tests in `tests/` and name them `test_*.py` or `*.spec.ts` (match the language).
- Include a short note on minimum coverage expectations if required.

## Commit & Pull Request Guidelines
No commit history is available to infer conventions. Until clarified:
- Use imperative commit messages, e.g., `Add batch rename CLI`.
- Include a short summary and testing notes in pull requests.
- Link issues or tickets when applicable.

## Agent-Specific Instructions
Keep this file current when project tooling or structure changes.
