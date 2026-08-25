---
name: karakeep
description: Save, search, or organize KaraKeep bookmarks and folders. Use when the user wants to save/bookmark/archive content to KaraKeep, find an existing bookmark, or pick the right folder.
---

# karakeep - save to / search KaraKeep

Three subcommands. Prints JSON (save) or tab/line lists (lists, search).

## Usage

    karakeep save   --url <url> [--title <t>] [--note <text|@file>] [--list "<name>" | --list-id <id>] [--asset <path>]... [--tag <t>]...
    karakeep lists  [filter]             # browse folders as "Parent > Name  [id]"; filter = case-insensitive substring
    karakeep search <query> [--limit N]  # full-text bookmark search -> "title<TAB>url<TAB>id"

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
- `--asset` uploads the image and attaches it (assetType `userUploaded`; shows in the bookmark's attachments).
- `search` is handy to check whether a link is already saved before saving again.
- Reads `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` from `~/.hermes/.env`.
