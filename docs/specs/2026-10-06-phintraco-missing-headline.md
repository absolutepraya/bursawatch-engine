# Phintraco missing headline repair

The [MGLV post](https://discord.com/channels/940285152335110204/1525102508714889257/1556844268474081353)
displayed `MGLV: MGLV` although its Quick Notes source supplied a descriptive
headline. The accepted selection contained no title. PR #64 preserved supplied
titles, but the active Telegram source-ingest prompt's JSON example still
omitted `title` despite requesting it in prose. Compatibility accepts missing
Phintraco titles, and the old renderer then falls back to the issuer name.

Include `title` in the active Market News JSON example. Keep titleless
Phintraco submissions accepted without another model call or delivery hold.
For newly prepared cards, prefer a supplied generated title, then the explicit
source headline from branded Notes, Quick Notes, or Company Update, then the
existing issuer-name or brand fallback. Read only the known headline slot,
never infer a story from body text. Keep source wording, amounts and names;
the shared component still owns common capitalization and card rendering.
Issuer cards use their exact ticker prefix; macro cards omit that prefix and
the price tracker. Unusable optional headlines leave delivery unchanged.

Preserve source identities, eligibility, routes, frozen configuration,
receipt checks, operation identities, quote data, and retry behavior.
Never rewrite an already frozen payload or edit a historical Discord message
as part of the code repair. Production deployment remains separately approved.

Regression coverage exercises source parsing, titleless submission,
persistence, selection reconstruction and rendering for all three supported
headline slots and both routes. It also checks the active prompt JSON,
quote-bearing subsidiary news, unusable fallback input, supplied-title
precedence, and verbatim retries of a previously frozen duplicate ticker.
