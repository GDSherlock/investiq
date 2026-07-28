# Upload Primary Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Upload as the first primary navigation section and route it to the existing unified upload page.

**Architecture:** Preserve the existing upload page at `/` and change only the shared navigation configuration. Protect the route and ordering contract with a focused source-level Node test.

**Tech Stack:** Next.js, React, TypeScript, Node test runner

## Global Constraints

- Continue on `feature/frontend-integration`; do not create or switch branches.
- Preserve and exclude unrelated dirty and untracked files.
- Do not change upload APIs, state management, storage, or analysis routes.

---

### Task 1: Upload navigation entry

**Files:**
- Modify: `apps/ui/src/app/NavBar.tsx`
- Test: `apps/ui/src/lib/calculation-logic.test.ts`
- Create: `docs/superpowers/specs/2026-07-28-upload-primary-navigation-design.md`
- Create: `docs/superpowers/plans/2026-07-28-upload-primary-navigation.md`

**Interfaces:**
- Consumes: existing root upload page at `/` and the `NAV_LINKS` array
- Produces: an `Upload` primary navigation link before `Overview`

- [x] **Step 1: Write the failing navigation contract test**

```ts
test('navigation exposes Upload before Overview and routes it to the unified upload page', () => {
  const navBarSource = readFileSync('src/app/NavBar.tsx', 'utf8');
  const uploadLink = "{ href: '/', label: 'Upload' }";
  const overviewLink = "{ href: '/dashboard', label: 'Overview' }";

  assert.ok(navBarSource.includes(uploadLink));
  assert.ok(navBarSource.indexOf(uploadLink) < navBarSource.indexOf(overviewLink));
});
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `npm run test:calculation`

Expected: FAIL because `NavBar.tsx` does not yet contain the Upload entry.

- [x] **Step 3: Add the minimal navigation entry**

```ts
const NAV_LINKS = [
  { href: '/', label: 'Upload' },
  { href: '/dashboard', label: 'Overview' },
];
```

Keep every existing navigation entry after Overview unchanged.

- [x] **Step 4: Verify GREEN and production build**

Run: `npm test`

Expected: all calculation and loading tests pass.

Run: `npm run build`

Expected: the Next.js production build succeeds.

- [x] **Step 5: Commit only the task files**

```bash
git add apps/ui/src/app/NavBar.tsx \
  apps/ui/src/lib/calculation-logic.test.ts \
  docs/superpowers/specs/2026-07-28-upload-primary-navigation-design.md \
  docs/superpowers/plans/2026-07-28-upload-primary-navigation.md
git commit -m "feat(frontend): add Upload to primary navigation"
```
