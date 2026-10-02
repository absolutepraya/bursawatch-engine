# Telegram Market News

Language for Phintraco and Tuntun news summaries and their reader-facing cards.

## Language

**Direct reporting voice**:
A factual news voice that begins with the issuer, action, or actual news subject. It does not require personal pronouns such as `saya` or `kami`.
_Avoid_: First-person perspective, publisher narration

**News summary**:
One to five source-grounded Indonesian sentences describing the selected news. Longer summaries preferably use two paragraphs grouped by subject, with a flexible threshold and no delivery blocking for paragraph style.
_Avoid_: Source transcript, investment recommendation

**Research attribution**:
Language identifying whose estimate or forecast is being described, preserving its period, units, and uncertainty. It distinguishes broker research from reported results and company guidance.
_Avoid_: Generic source introduction, established result

**Issuer news card**:
A news card routed around one identified IDX issuer, with its factual summary, price tracker, and source link.
_Avoid_: Every ticker mention, macro card

**Macro news card**:
A news card about a broader policy, legal, regulatory, economic, or multi-company subject. It has a summary and source link without issuer market data, even when an issuer is mentioned.
_Avoid_: Issuer news card, tickerless-only news

**Price tracker**:
The latest available IDR price and absolute and percentage changes over 1D, 1W, 1M, and 3M, with direction emojis and existing unavailable-value placeholders. Its values come from deterministic market enrichment.
_Avoid_: Model-generated prices, price forecast

**Ringkasan marker**:
The single `*(Ringkasan)* ` prefix introducing a rendered news summary. It is separate from the summary's factual prose.
_Avoid_: Classifier-authored heading, per-paragraph label
