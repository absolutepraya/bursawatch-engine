# AMMN Swing Board repair

Status: implementation and repair manifest prepared for review. No production
Board state or Discord message has been changed.

## Reviewed source event

Phintraco Telegram message `34908` is `AMMN - Hold/Trading Buy`. In this
watcher's vocabulary, `Hold/Trading Buy` is a BUY subtype. The message contains
Entry `4360`, Stop-loss `<4200`, Target 1 `4700`, and Target 2 `5000`.

The reviewed manifest is
`cron-dc-swing-board/backfills/2026-09-23-ammn-primary-repair.json`. It selects
only source message `34908` as a BUY. Applying it uses the regular Board owner
event path. When it promotes the existing source-only AMMN episode, the owner
reconciles already-attached later Phintraco social outcomes against this plan.
This preserves the existing topic and source history while allowing the
explicit final-target outcome to resolve the plan.

## Formatting repair

The affected Phintraco source reply has no blank line between `Last updated:`
and `[View in Telegram]`. New fallback-rendered Phintraco replies now insert
exactly one blank line there. The existing `migrate-format --apply` operation
also rewrites completed history replies in place, so it can correct that
already-posted reply without posting a replacement.

## Approved execution sequence

After code review and deployment, read the current AMMN episode, its source
events, the target Discord messages, and the pending Board outbox. Run the
manifest dry-run and confirm it parses only message `34908` as a BUY. Review the
`migrate-format` dry-run counts because that existing command may rewrite other
completed Board cards and replies as well. Apply either operation only after
separate explicit approval of its live scope. Then read back the AMMN starter,
source history, footer spacing, lifecycle tag, source links, and outbox state.
