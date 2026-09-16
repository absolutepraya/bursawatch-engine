# Shared cash-Swing renderer

`bin/swing_format.py` is the provider-neutral presentation contract for
cash-equity Swing source messages. Phintraco Daily and Kelas Investasi GTW use
it now, while future adapters such as BRI Danareksa can supply normalized
fields without changing the shell.

The runtime copy lives at:

```text
~/.agents/skills/swing-format/bin/swing_format.py
```

Deploy it before the watcher files that import it:

```bash
./deploy.sh swing-format
```

The renderer owns heading, byline fallback, spacing, source-status emoji,
source timestamp, the All-only Board link, and source footer grammar. Provider
adapters retain their own source fields and summaries.

`canonicalize_phintraco_message()` is the bounded legacy migration path for
already-published Phintraco BUY, HOLD, and REMINDER text. It preserves source
values while normalizing ticker-first titles, outcome-first follow-up titles,
analyst/institution bylines, dates, inline emoji spacing, factual source
status, and provider footers.

`bin/bri_adapter.py` defines the future BRI Danareksa normalized adapter. The
live WhatsApp watcher does not import it yet, so BRI routing and delivery stay
unchanged until that separate integration is approved.
