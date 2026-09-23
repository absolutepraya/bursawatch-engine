# Recommended source identity assets

Reviewed 17 September 2026. This directory contains nine public X profile images and two official institution logos. The BRI Danareksa recommendation reuses the existing logo under `public/brokers/`. These images identify their sources; they are not invented portraits or a claim of endorsement. Preserve original colors and proportions, with the directory's circular crop for public avatars.

- Bank Indonesia: logo from https://www.bi.go.id/SiteAssets/logo-bi.png. Its own cash-service page identifies @bank_indonesia as its official account: https://www.bi.go.id/en/layanan/kas-bi/default.aspx.
- OJK: logo from https://ojk.go.id/_catalogs/masterpage/responsive-master/images/logo.png. Its own directory identifies @ojkindonesia: https://ojk.go.id/en/berita-dan-kegiatan/publikasi/Pages/OJK-Services-and-Information-Quick-Access.aspx.

Institution recommendations provide first-party institutional context; team selections identify public accounts chosen by the team. Neither label rates investment performance, guarantees accuracy or implies a partnership. Additional personal accounts require public identity/background evidence before joining the curated directory. Users may independently add public sources.

## Team watchlist

The user requested the public accounts already selected in their friend's Hermes setup. On 18 September 2026, the catalog was aligned with Bursawatch backend configuration at `absolutepraya/bursawatch` commit `f36823f`: 10 X accounts, seven Instagram accounts and one WhatsApp Channel. Only public identities and topic keys are projected into this web package; no delivery IDs, newsletter IDs, credentials or personal runtime state are copied. Tests compare this projection with a pinned allowlisted public fixture. They do not require the backend service, import its private configuration, or detect later backend changes. Future catalog updates require a reviewed public-field refresh.

Profiles included: @Kutekians, @rickyho_1989, @writingtorch, @ArvinHonami, @doktermarket, @txthariansaham, @wavetiga, @aldotjahjadi8 and @KobeissiLetter. Their public profile metadata was fetched through https://api.fxtwitter.com/<handle>, checking returned handle equality. Images were fetched from the returned pbs.twimg.com profile-image URL, resized to 160px PNG, and retain the exact image origin in their EXIF description. Biographical copy paraphrases self-described profile content; it is not independent credential verification.

The configured @InsiderTrackX account returned 404 from the profile lookup during the earlier image review. This does not establish permanent unavailability. It is now included from the canonical reviewed configuration, using initials instead of a photograph. Its inclusion does not claim a successful new profile lookup, verified identity or live source health.

Instagram selections are @beyondthefundamental, @investart_id, @avenirresearch.id, @acresresearch, @sectorsapp, @cukhurukuque and @notintofinance. They use the public names and identities reviewed at `f36823f`, with initials rather than unreviewed photographs. Descriptions explain configured coverage, not independently verified credentials or investment performance. The stable profile ID `avenirresearch_id` is distinct from its public handle `avenirresearch.id`.

BRI Danareksa's public WhatsApp Channel link is the one configured in the reviewed source. Its logo and provenance remain under public/brokers. All individual/publication accounts and the channel carry “Team selection,” not an official or independently verified badge.
