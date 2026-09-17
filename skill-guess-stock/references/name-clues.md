# Name clue matching

Use this reference when the user gives a sentence or phrase instead of a chart
image. Infer an active IDX company through a direct word, synonym, sound,
abbreviation, or playful phrase.

## Search order

1. Direct company-name substring or near-exact Indonesian or English synonym
2. A meaningful word inside the legal name, ignoring generic words such as PT,
   Tbk, Indonesia, Global, and Prima
3. A ticker that directly spells the clue or a familiar shortened form
4. A phonetic clue, pun, or intentionally misspelled product or brand
5. A phrase made from multiple company-name words

Return a short ranked set when multiple names fit. A weak semantic mapping is a
lead, not confirmation.

## Exact phrase versus exact answer

A search result that repeats the user's whole clue beside a ticker is only a
lead. Resolve the underlying source reference first, such as a brand tagline or
product name, then map that reference to the ticker. For example,
`minum makanan bergizi` points to Energen and therefore `$ENRG`, not `$BUMI`
merely because a Stockbit result happened to contain both words. Require the
semantic mapping plus an issuer or group clue before declaring a result.

## Examples

- `nah semoga ini bersinergi` -> `$INET`, Sinergi Inti Andalan Prima Tbk
- `panjang penggaris` -> `$INCI`, Intanwijaya Internasional Tbk
- `roda 4, besar` -> `$TRUK`, Guna Timur Raya Tbk
- `tisu bayi` -> `$MITI`, Mitra Investindo Tbk, from the Mitu Tisu Baby wordplay
- `teman mas` -> `$TMAS`, Temas Tbk
- `ketar ketir` -> `$KETR`, Ketrosden Triasmitra Tbk
- `Upin Ipin jgn laju-laju` -> `$LAJU`, Jasa Berdikari Logistics Tbk
- `sumber mineral` -> `$SMGA`, Sumber Mineral Global Abadi Tbk
- `Mas Agung` -> `$APLN`, Agung Podomoro Land Tbk
- `guru BK` -> `$BSBK`, Wulandari Bangun Laksana Tbk

## Verification

Read the current IDX company list and verify that the ticker and legal company
name are still active before finalizing a clue answer. Do not use price charts
unless the user also supplies a chart clue.
