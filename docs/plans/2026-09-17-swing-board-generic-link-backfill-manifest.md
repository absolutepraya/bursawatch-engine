# Swing Board generic-link backfill manifest

Status: prepared for review. No bootstrap, Board write, or Discord message edit
has occurred from this manifest.

## Scope and invariant

The ten listed Yanto-owned messages in `#id-stocks-swing` contain the old
generic Board channel URL. Each must retain its own Discord message identity
and be edited in place only after its exact Board topic is materialized. No
step posts a new All Swing message.

The reviewed Phintraco input lives in
`cron-dc-swing-board/backfills/2026-09-17-generic-board-links-phintraco.json`.
It selects source messages individually, rather than selecting one latest
candidate per ticker. The two DSSA updates are therefore separate immutable
source events even though they land in the same ticker topic.

| All Swing message | Source message | Seed before source event | Resulting Board topic and tier | In-place edit |
| --- | --- | --- | --- | --- |
| `1547070401920761879` BIPI | Phintraco `35095` reminder | `34460` complete BUY | `BIPI`, Primary plan | Replace only the generic Board URL with BIPI's direct topic URL. |
| `1547105477492482079` COIN | Phintraco `35101` status | None. A complete original BUY is not present in the reviewed source chain. | `COIN`, Chart context | Replace only the generic Board URL with COIN's direct topic URL. |
| `1547136473281597450` NCKL | Phintraco `35105` final reminder | `34499` complete BUY | `NCKL`, Resolved | Replace only the generic Board URL with NCKL's direct topic URL. |
| `1547429179119640580` CUAN | Phintraco `35134` final reminder | None. Its individual original BUY is unavailable, and the prior multi-ticker idea is not a valid single-ticker plan. | `CUAN`, Chart context | Replace only the generic Board URL with CUAN's direct topic URL. |
| `1547432971814830130` PTRO | Phintraco `35138` reminder | `34928` status that refers to a prior multi-ticker idea, retained as source-only context | `PTRO`, Chart context | Replace only the generic Board URL with PTRO's direct topic URL. |
| `1547445575270531232` UNTR | Phintraco `35140` final reminder | `34800` complete BUY | `UNTR`, Resolved | Replace only the generic Board URL with UNTR's direct topic URL. |
| `1547508884439306340` DSSA | Phintraco `35149` status | None | `DSSA`, Chart context | Replace only the generic Board URL with DSSA's direct topic URL. |
| `1547804915806511197` DSSA | Phintraco `35172` reply-status | `35149` is also submitted as a distinct source-only event | Existing `DSSA` topic, Chart context | Replace only the generic Board URL with that same DSSA direct topic URL. |
| `1548881848602460171` AMMN | Phintraco `35197` final reminder | `34908` complete BUY | `AMMN`, Resolved | Replace only the generic Board URL with AMMN's direct topic URL. |
| `1549133440140451891` FUTR | Kelas Investasi `10632` GTW | None | `FUTR`, Supporting setup | Replace only the generic Board URL with FUTR's direct topic URL. |

The six complete Phintraco BUY seeds are Board prerequisites rather than All
message edits. They must not emit an All Swing resend. A source-only status or
reminder is intentionally submitted as `social`, so it remains Chart context
and never fabricates a Primary Plan or price checkpoints.

## Ordered execution, after separate production approval

1. Read all ten All Swing messages and verify that Yanto still owns each exact
   message ID and that its Board field is still the generic channel URL.
2. Query the Board state for all nine tickers. Skip an existing matching topic,
   and stop if an existing topic conflicts with the reviewed source identity.
3. Copy the reviewed Phintraco JSON manifest to a protected temporary VPS
   path, then run its manifest dry-run with a 30-session window. Its report
   must contain all fourteen listed source events and preserve both DSSA IDs.
4. Apply the Phintraco manifest only when that report matches this document.
   The owner creates only missing topics and normal Board replies. It does not
   post to All Swing.
5. Construct FUTR through the existing GTW `board_payload` adapter and submit
   it once to the Board owner. It must create only the missing `FUTR`
   Supporting setup topic.
6. Drain until each topic has a direct topic URL. Re-read Board state and
   verify that the expected source event identities are durable and that the
   outbox has no pending work for this backfill.
7. For each target All message, replace its Board field with the raw direct
   Discord topic URL. Do not wrap a Discord Board URL in angle brackets, since
   Discord renders the raw URL as the desired topic button. Keep Telegram URLs
   angle-bracketed. Re-read every edited message and verify the direct button.
8. Confirm that the ten original All message IDs remain the only All messages
   touched and that no duplicate All Swing alert exists.

If any source message cannot be parsed, a topic cannot be materialized, an All
message is no longer Yanto-owned, or its existing content no longer matches
this manifest, stop before any edit. Report the exact source or Discord ID and
choose a new reviewed corrective action rather than creating a replacement
alert.
