---
name: karakeep
description: Save, search, or organize KaraKeep bookmarks and folders. Use when the user wants to save/bookmark/archive content to KaraKeep, find an existing bookmark, or pick the right folder.
---

# karakeep - save to / search KaraKeep

Three subcommands. Prints JSON (save) or tab/line lists (lists, search).

## Usage

    karakeep save   --url <product-url> [--title <t>] [--note <text|@file>] [--source <url>] [--list "<name>" | --list-id <id>] [--asset <path>]... [--tag <t>]...
    karakeep lists  [filter]             # browse folders as "Parent > Name  [id]"; filter = case-insensitive substring
    karakeep search <query> [--limit N]  # full-text bookmark search -> "title<TAB>url<TAB>id"

## Choosing the URL to save (do this first)

`--url` is what KaraKeep unfurls for the preview image and the link you click to reach the
thing. Save the URL that points most directly at the **specific item**, with a real preview
image. A social post or profile (TikTok, IG, X) is almost never the right `--url` - it's
where you *found* the thing, not the thing itself. Saving the creator's profile (e.g.
`@lythwatches` for a Seiko Presage post) is wrong; save the watch's own page.

1. Identify the specific item - the caption/screenshot usually names it (e.g. "Seiko
   Presage Iceberg"). If the exact page isn't already in hand, find it with web search /
   `brave-search` (and `google-maps` for hotels/restaurants/places).
2. **Physical products & experiences** (watches, gadgets, hotels, flights, restaurants) ->
   a link that opens *that exact item*:
   - the official product page (e.g. `seikowatches.com/.../presage`), or
   - a store / booking deep-link to the item: a hotel -> the tiket.com (or Booking) page
     for *that hotel*, not tiket.com's home; a watch -> a retailer's product page.
   - Fall back to the brand homepage only if no specific page exists.
3. **Software / frameworks / AI agents / paid services** -> the store / marketplace /
   pricing / product page over the bare homepage, *especially* when the homepage has no
   product image (a logo-only unfurl is wasted). e.g. a VS Code extension -> its Marketplace
   listing; an npm package -> its npm page; an app -> its App Store page.
4. The chosen URL must unfurl to a **relevant** preview image. If a homepage would only show
   a generic logo, go one level deeper to a page that previews the actual item. When unsure
   whether a link will unfurl well, open it with the `browser` tool to confirm before saving.

Keep provenance: pass the original social link via `--source <url>` (appended to the note as
a `Source:` line) so you don't lose where it came from - but it is never the `--url`.

## Folder resolution + disambiguation

- `--list "<name>"` resolves a folder by exact name (case-insensitive).
  - unique match -> used.
  - not found -> errors (browse with `karakeep lists "<name>"`).
  - **ambiguous** (KaraKeep allows duplicate names, e.g. `Gift > Watch` and `Polymarket > Watch`)
    -> prints each candidate with its parent path + id and exits non-zero, creating nothing.
    Pick the one that fits the content (a wristwatch post -> `Gift > Watch`) and re-run with
    `--list-id <id>`. If genuinely unsure which folder, ask the user.
- `--list-id <id>` skips name resolution (use after disambiguating).

## Other behaviour

- `--note @file` reads the note body from a file (use for multi-line markdown).
- `--source <url>` appends a `Source: <url>` line to the note - use it for the social link
  the item came from, keeping `--url` free for the actual product/store page.
- `--asset` uploads the image and attaches it (assetType `userUploaded`; shows in the bookmark's attachments).
- `search` is handy to check whether a link is already saved before saving again.
- Reads `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` from `~/.hermes/.env`.
