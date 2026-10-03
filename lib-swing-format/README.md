# Shared cash-Swing renderer

`bin/swing_format.py` is the provider-neutral presentation contract for
cash-equity Swing source messages. Phintraco Daily and Kelas Investasi GTW use
it now, while future adapters such as BRI Danareksa can supply normalized
fields without changing the shell.

The runtime copy lives at:

```text
~/.agents/skills/lib-swing-format/bin/swing_format.py
```

Deploy it before the watcher files that import it:

```bash
./deploy.sh lib-swing-format
```

The renderer owns heading, byline fallback, spacing, source-status emoji,
source timestamp, the temporary All-only Discord forum marker, direct-topic
link replacement, and source footer grammar. Provider adapters retain their own
source fields and summaries.

`canonicalize_phintraco_message()` is the bounded legacy migration path for
already-published Phintraco BUY, HOLD, and REMINDER text. It preserves source
values while normalizing ticker-first titles, outcome-first follow-up titles,
analyst/institution bylines, dates, inline emoji spacing, factual source
status, and provider footers.

`bin/bri_adapter.py` defines the future BRI Danareksa normalized adapter. The
live WhatsApp watcher does not import it yet, so BRI routing and delivery stay
unchanged until that separate integration is approved.

`bin/source_plan.py` validates LLM-selected level fields against unchanged source
character spans. It does not extract source plans or alter Board evaluation.
`source_plan_display` supplies Entry, Stop-loss and Target 1 placeholders, then
explicitly supplied numbered targets and additional stops. Source ranges and
comparators remain intact. `fields_from_canonical_message` reads only the
already canonical rendered fields for optional Board presentation. Raw source
text and legacy plan records remain authoritative evidence.

`frozen_presentation.py` validates closed version-2 presentation records and
removes only the Board line for source-context copies. Source owners freeze
messages and destinations before delivery; the library has no state or send
authority. Legacy records remain on their original rendering path.
