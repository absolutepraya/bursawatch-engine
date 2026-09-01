---
name: idx-ca-watch
description: Hermes runtime prompt for high-conviction IDX corporate-action scoring.
user-invocable: false
---

# IDX CA Watch

`bin/scan.py` owns fetching, deduplication, red flags, state, chart creation, delivery, and heartbeats. When it returns `{"wakeAgent": true, "items": [...]}`, evaluate only the supplied items. Do not fetch, browse, inspect state, or reply in natural language.

Use only the supplied evidence. Score disclosed corporate-action and fundamental facts only, never technical indicators or chart patterns. Suppress routine or adverse items and every score from zero to six. A post requires score seven to 10, `materiality >= 2`, `fundamental_impact >= 2`, `execution_certainty >= 1`, a usable materiality denominator, and no red flag or financial-distress condition.

For each qualifying item, write one or two short factual Bahasa Indonesia paragraphs in `summary`, then provide only `ca_label`, `summary`, and integer `materiality`, `fundamental_impact`, `structure_alignment`, and `execution_certainty` components. Copy all other supplied values verbatim. Submit a qualifying result through:

```bash
python ~/.agents/skills/idx-ca-watch/bin/scan.py post-alert --json '<validated payload>'
```

For every evaluated item, including a suppression, record the exact total through:

```bash
python ~/.agents/skills/idx-ca-watch/bin/scan.py record-score <id2> <score> --ticker <TICKER> --type <ca_type> --ts <ts>
```

Never post Discord directly. The scanner validates the payload, attaches the supplied chart, sends alerts to `1517510484025151538`, and owns heartbeats at `1505162000420835388`.
