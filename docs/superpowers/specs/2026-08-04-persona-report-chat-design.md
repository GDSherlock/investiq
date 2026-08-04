# Persona Report Chat Design

**Date:** 2026-08-04

**Status:** Approved for implementation planning

## Goal

Replace the current report-generator workspace with a simple ChatGPT-style
report conversation. The selected persona determines the available report
prompts and the focus of new AI responses. Reports appear directly as rich
assistant messages that users can refine through the same chat, copy into
Microsoft Word, or download as `.docx` files.

## Approved Product Decisions

- Each persona has one fixed default report type.
- The Reports page is a single scrolling chat interface; there is no separate
  report preview pane.
- Reports appear directly as assistant messages in the shared conversation.
- All personas share the same report-chat history.
- Switching persona changes the starter prompts and future AI perspective but
  does not clear existing messages.
- The global persona selector moves from the top navigation into the Reports
  chat composer.
- Persona remains global application state, so a selection made on Reports also
  affects AI assistants on other pages.
- Reports are generated in English.
- Reports render as rich content, not visible Markdown.
- Every report message supports rich-text copy and `.docx` download.
- The LLM may narrate only existing model evidence or facts supplied by the user
  in the conversation.
- User-supplied facts become eligible report context immediately; there is no
  separate confirmation-card flow.
- Topics without supporting data are omitted rather than described as missing.
- Model-derived and user-provided claims remain visibly distinguishable.
- There is no report workspace, draft/publish workflow, or separate visible
  version manager. Earlier report messages remain naturally available in chat.

## Scope

This feature covers:

- moving the persona selector into the Reports chat composer;
- persona-specific starter prompts;
- one persistent report conversation shared across personas;
- report generation and conversational refinement;
- rich report-message rendering;
- inline citations;
- copying a report as Word-compatible rich text;
- downloading an individual report message as `.docx`;
- loading only canonical evidence associated with the active model and
  calculation identity.

It does not cover:

- changing workbook extraction, chunking, calculation, Sensitivity, or Monte
  Carlo logic;
- writing user-provided report facts back into the financial model;
- arbitrary report-type selection independent of persona;
- report approval workflows;
- collaborative editing;
- report folders, dashboards, or a visible version browser;
- PDF export;
- multilingual report generation.

## User Experience

### Page structure

The Reports page contains:

1. a compact header identifying the active model and calculation run;
2. one vertically scrolling message history;
3. persona-specific starter prompts when appropriate;
4. a sticky chat composer;
5. a persona selector beside the composer input.

There is no second report pane. Ordinary assistant responses and generated
reports both appear in the same message stream. A generated report message is
visually wider than a normal chat response and includes its report title,
persona label, inline sources, `Copy`, and `Download Word` actions.

### Primary flow

1. The user opens Reports.
2. The page restores the shared conversation for the active model.
3. The current persona determines the starter prompts.
4. The user clicks a starter prompt or types a request.
5. The clicked starter prompt is sent as a normal user message.
6. The AI returns the generated report as a rich assistant message.
7. The user continues the conversation to shorten, expand, correct, or add
   information.
8. The AI returns an updated report as a new assistant message in the same
   history.
9. The user copies or downloads any report message directly.

### Persona switching

The existing global persona selector is removed from `NavBar.tsx` and rendered
inside the Reports composer. `PersonaContext` remains the global source of
persona state and retains its current persistence behavior.

Switching persona:

- preserves the complete shared conversation;
- immediately replaces the starter prompts;
- changes the persona applied to the next request;
- does not rewrite persona labels on historical messages;
- continues to affect persona-aware assistants outside Reports.

Every assistant report message stores and displays the persona used when it was
generated.

## Persona Prompt Registry

The client sends a persona ID. The backend selects the corresponding approved
persona prompt; it must not trust a client-supplied system prompt.

| Persona | Primary prompt | Report focus |
|---|---|---|
| Investment Manager | Generate an Investment Committee Paper | Decision, returns, downside risk, and approval conditions |
| CFO | Generate a CFO Funding Note | Funding, liquidity, capital structure, DSCR, and covenants |
| Board Director | Generate a Board One-Pager | Concise decision headline, top risks, and management actions |
| Financial Analyst | Generate a Technical Sensitivity Summary | Assumptions, sensitivities, calculation logic, and sources |
| Project Owner | Generate a Variance and Action Report | Variances, milestones, risks, owners, and actions |

Each persona may expose two or three secondary starter prompts already aligned
with its existing `starter_prompts` and focus. Starter prompts are convenience
messages, not a separate generation workflow.

The selected persona owns the report type. If a user asks for another persona's
fixed report type, the assistant asks the user to switch persona instead of
silently changing the report contract.

## Report Content Rules

Reports use normal document structure: title, headings, paragraphs, numbered or
bulleted lists, and tables when the evidence is naturally tabular. The UI must
not display Markdown source.

The report generator may use:

- validated workbook metadata;
- canonical calculation inputs and outputs for the active calculation run;
- matching completed Sensitivity artifacts;
- matching completed Monte Carlo artifacts;
- facts explicitly supplied by the user in the current conversation.

The generator must:

- omit sections that have no supporting evidence;
- avoid `Unavailable` filler paragraphs;
- avoid inventing values, dates, risks, mitigations, owners, or approval rules;
- distinguish a factual threshold result from an unsupported approval decision;
- preserve source identity for every material financial claim;
- treat later user corrections as superseding earlier user statements in new
  responses without deleting the original chat history;
- represent conflicts between model evidence and user statements explicitly
  rather than silently replacing the model value.

User-provided facts remain report-chat context only. They do not mutate the
canonical model or calculation results.

## Citations

Report messages use concise inline references:

- `[M#]` for model-derived evidence;
- `[U#]` for user-provided evidence.

The rendered message provides source details on interaction. A compact
`Evidence Sources` section at the end of the report resolves each reference to
its model artifact, workbook source, or user message and timestamp.

Rich-text copy and Word export preserve both the inline reference and the
evidence list.

## Minimal Technical Design

### Frontend components

Keep the page small and focused:

- `ReportChatPage`: loads and displays the thread;
- `ReportMessageList`: renders ordinary and report messages;
- `PersonaReportStarters`: renders prompts for the selected persona;
- `ReportChatComposer`: owns input, submit, retry, and the relocated persona
  selector;
- `RichReportMessage`: renders structured report content and copy/download
  actions.

The existing global `PersonaContext` remains in place. The top-level navigation
stops rendering its persona row.

### Backend boundaries

The backend needs only three focused responsibilities:

1. load and persist the shared report thread and its messages;
2. assemble canonical evidence matching the active analysis identity and add
   user-provided conversation context;
3. call the report model with the server-owned persona prompt and return a
   validated structured report message.

The current canonical evidence path remains the source of model-derived facts.
The legacy free-form `parsed_json` report route must not become the source of
truth for current calculation results.

### Message contract

Each persisted message records at least:

- message ID and thread ID;
- role;
- plain user text or structured assistant content;
- persona ID used for that message;
- creation time;
- active model and calculation identity;
- citation metadata;
- whether the assistant message contains a downloadable report.

Assistant report content uses validated document blocks rather than Markdown or
arbitrary HTML. The initial block set is limited to headings, paragraphs,
lists, tables, and citation references.

One shared thread is restored for the current user and model version. Persona
is message metadata, not part of the thread key.

### Word-compatible output

`Copy` writes both `text/html` and `text/plain` clipboard representations so
Microsoft Word retains headings, paragraphs, lists, tables, and citations.

`Download Word` requests a `.docx` generated from the selected report message's
validated document blocks. Exporting an earlier report message must reproduce
that message, not silently export the latest response.

## Data Flow

```text
persona selection + user message
              |
              v
persist shared chat message
              |
              v
load active canonical evidence + relevant chat context
              |
              v
apply server-owned persona report prompt
              |
              v
validate structured assistant response and citations
              |
              v
persist and render assistant/report message
              |
              +--> rich-text copy
              +--> DOCX download
```

## Failure Behavior

- If extraction is incomplete or failed, report generation remains disabled and
  the page links back to model setup.
- If no ready calculation run exists, the page keeps chat history visible but
  does not offer model-derived report generation.
- An AI failure preserves the user message and presents a retry action.
- An invalid structured response or unsupported citation is not rendered as a
  report; the user receives a concise failure message and retry action.
- A failed copy or DOCX export does not alter the conversation.
- Requests are idempotent so a network retry does not duplicate a user message
  or report.
- Data from another model version or calculation run is never included.

## Testing and Acceptance

### Frontend contracts

- the persona selector no longer renders in the top navigation;
- the Reports composer renders the selector and updates global persona state;
- switching persona changes starter prompts without clearing messages;
- historical messages preserve their original persona labels;
- a clicked starter is submitted as a normal user message;
- structured report blocks render without visible Markdown;
- report messages expose Copy and Download Word actions;
- copy writes Word-compatible rich text;
- loading, retry, empty, and blocked-analysis states render correctly.

### Backend contracts

- persona IDs resolve to the correct server-owned report prompt;
- all personas share one thread for the same user and model version;
- messages retain persona and active calculation identity;
- evidence assembly excludes stale, failed, ambiguous, and unavailable data;
- unsupported report sections are omitted;
- model and user citations remain distinguishable;
- invalid or uncited material claims fail response validation;
- duplicate requests are idempotent;
- DOCX export preserves report structure and citations.

### End-to-end acceptance

For one ready persisted model:

1. generate an Investment Committee Paper;
2. switch to CFO without losing history;
3. generate a CFO Funding Note in the same thread;
4. add a user-provided funding fact and request an updated note;
5. verify model and user sources are distinguished;
6. copy the result into Word with formatting preserved;
7. download and open the `.docx` successfully;
8. verify absent evidence is omitted rather than narrated.

## Implementation Constraint

Implementation must preserve the current workbook extraction and calculation
contracts. Existing unrelated worktree changes must remain untouched, and the
feature should be delivered through focused frontend, API, persistence, export,
and contract-test changes only.
