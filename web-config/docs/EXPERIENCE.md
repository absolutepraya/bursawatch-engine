# Product experience: sample workspace

## Scope

`/workspace` is the authenticated operator workspace. Its seven destinations
are Overview, Sources, Workflows, Jobs, History, Published and Account, in that
order. Supabase Auth and the same-origin `/api/control` proxy supply its
protected records and supported writes.

`/app` is the no-login Sample workspace linked from the landing. It uses the
same navigation, layout and workspace components with synthetic in-memory
fixtures. Its request function has the same shape and `WorkspaceError`
behavior as `controlBrowser()`. It does not create an Auth client, call
`/api/control`, or perform network writes. Watcher configuration and Source
Catalog edits use the real schemas, update the fixture, and confirm by reading
the updated fixture.

## Navigation and routes

The sample presents the same seven destinations and order as `/workspace`:

- Overview
- Sources, with Securities, Institutions, and People & Org
- Workflows, with the eight supported watcher editors and their input,
  processing and output summaries
- Jobs
- History
- Published
- Account

The landing destination remains `/app`. Legacy Insights and Overview paths
redirect to Overview; Discover, Following and Securities paths redirect to
Sources; Automations and configuration paths redirect to Workflows; Activity
and Logs redirect to History; Settings paths redirect to Account. Existing
`/workspace` routing is unchanged.

## Sample records and edits

Use public landing examples for Sources and Published, including TRUK, HRTA,
the ENRG plan and its target update. Mark every record as a sample. The
Bursawatch Pagi example uses the landing's `BURSAWATCH PAGI`, `ROTASI SEKTOR`
and `ROTASI KONGLO` format, with its dummy figures and an example label.
The reviewed public source fixture is approved sample input. Do not include
private configuration, destinations, credentials, sessions or runtime state.

Only real supported editor fields are interactive. Per-source post summaries
and compatible Source Catalog endpoint capabilities can be changed in the
sample. Catalog capability settings record source intent only, they do not
create a live source connection or attach a People & Org identity to a watcher
profile. The product has no separate evening digest or clock-time or weekly
interval control for the fixed morning brief. Explain these limits in the
sample and leave them read-only. Source Catalog and watcher edits remain in the
current in-memory sample session, use revision validation and read-after-write
confirmation, and never create an active source connection.

Jobs and History are read-only sample records. Fixed jobs and viewer sessions
have no save controls. Label synthetic records so they cannot be mistaken for
real jobs, runs, deliveries or connections. The Account view contains no
session or account identifier. Account access and Discord setup belong to the
authenticated workspace.

## Interaction and accessibility

Use the shared workspace components and Hanken Grotesk visual system. Keep all
seven labeled destinations visible in the mobile adaptive grid, preserve 44px
targets and visible focus, and support 375px layouts, enlarged text and
reduced motion. Sample-only styling stays under `src/app/app/`; it does not
add motion beyond the workspace motion budget.

Behavioral checks cover fixture validation, read-after-write updates, sample
navigation, read-only Jobs and History, legacy redirects, and zero requests to
`/api/control`. The authenticated `/workspace` smoke check continues to use
intercepted synthetic Auth and API responses.
