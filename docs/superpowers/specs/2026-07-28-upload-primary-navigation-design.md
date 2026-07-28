# Upload Primary Navigation Design

## Goal

Expose the existing unified upload and calculation-preparation page as the first
primary navigation section, immediately before Overview.

## Approved approach

Keep the upload page at `/` and add an `Upload` entry before the existing
`Overview` entry in `NavBar.tsx`. The root page, upload orchestration, API calls,
storage behavior, and analysis routes remain unchanged.

The existing active-link rule already treats `/` as an exact match, so Upload is
active only on the root page and does not become active on the analysis routes.

## Verification

- Add a navigation contract test that verifies Upload points to `/` and appears
  before Overview.
- Run the complete frontend test suite.
- Run the production frontend build.
