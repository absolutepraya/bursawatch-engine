---
name: karakeep
description: Save or bookmark a link (with optional images and a note) to KaraKeep, into a named folder. Use when the user wants to save, archive, or remember content to KaraKeep.
---

# karakeep — save to KaraKeep

Creates a link bookmark, optionally attaches images and sets a note/title, and files
it into a named list (folder). Prints `{bookmarkId, viewUrl}`.

## Usage

    karakeep save --url <url> [--title <t>] [--note <text|@file>] \
                  [--list "<folder name>"] [--asset <path>]... [--tag <t>]...

## Behaviour

- `--list` resolves the folder by exact name. If it does not exist, or the name is
  ambiguous (KaraKeep allows duplicate names), the command errors — ask the user
  which folder, or create it first.
- `--note @file` reads the note body from a file (use for multi-line markdown).
- `--asset` uploads the image and attaches it to the bookmark (assetType `userUploaded`; shows in the bookmark's attachments).
- Reads `KARAKEEP_API_KEY` + `KARAKEEP_ADDR` from `~/.hermes/.env`.
