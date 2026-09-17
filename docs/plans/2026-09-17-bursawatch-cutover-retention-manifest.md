# Bursawatch cutover retention manifest

Status: read-only VPS audit snapshot on 17 September 2026. No directory,
state, scheduler, wrapper, service, or process was changed.

The old runtime directories are retained as rollback material. A later
recoverable cleanup must refresh every checksum and reference scan below before
moving anything to Trash.

## Retained runtime directories

Tree hashes are SHA-256 of sorted per-file SHA-256 records. They identify the
directory snapshot without copying its contents into this repository.

| Retained directory | Files | Bytes | Tree SHA-256 |
| --- | ---: | ---: | --- |
| `~/.agents/skills/idx-market-news-watch` | 32 | 544,217 | `d08fa14dc42defda66a4f7c35b72d708d4cd99739ce9fa730e20556e87fe863e` |
| `~/.agents/skills/idx-swing-plan-board` | 27 | 453,671 | `4b4678bd3a4b4b36b32d47b862fac3a533b048f2a40b80f0c20d18742ed937cd` |
| `~/.agents/skills/idx-swing-watch-phintraco-daily` | 9 | 165,587 | `ef28b61c76bcb14e560207ca866d12c04c4c76c6cd1f6b5e8c744914ab4c7da0` |
| `~/.agents/skills/instagram-post-watch` | 172 | 799,729 | `aee2eb955d9c11220eb8153540ea83983288ce0f1fa9cd601e4cc8020a5dbd15` |
| `~/.agents/skills/kelas-investasi-gtw-watch` | 28 | 257,795 | `c1f98f6288d6c7aef8b4d4a5e389419880399413e135bbed3a09e212367a6cbd` |
| `~/.agents/skills/whatsapp-channel-watch` | 28 | 159,376 | `6cdb4deeb3b3300acd3d11813964a34172d9695e756dc24527d14c8147ce82e0` |
| `~/.agents/skills/x-post-watch` | 38 | 2,123,767 | `8bab9a9afb4752c54782085fd6ba8826a4f2c5daa7ab1b23778a7f4e4b8c1e2d` |

## Retained state and compatibility boundaries

| Legacy runtime | Retained state | Snapshot checksum | Cleanup status |
| --- | --- | --- | --- |
| Market News | `~/.hermes/state/idx-market-news.json` | 1,167,311 bytes, `7dcc597c821c94cadaac4a154d87b0c180d08234d6ce1c207035043d0350e1b7` | Current Bursawatch Market News and watchdog deliberately use this compatibility state. Do not clean. |
| Swing Board | `~/.hermes/state/idx-swing-board.sqlite3` and `idx-swing-board-media` | DB 458,752 bytes, `76e53ef2a2c1b01cc984d976c9a5c3f981e11587f855a7c44d9586c204d8190f`; media 6,651,455 bytes, `96454fdb16d314313bee37803dbe2b8dff1d1480f05496414a6fb5516333a66e` | Current Bursawatch Board deliberately owns these paths. Do not clean. The separate empty `idx-swing-plan-board.sqlite3` is only a future cleanup candidate. |
| Phintraco Swing | Internal `idx-swing-watch-phintraco-daily/state` | 826 bytes, `75b769c7b8162d7ffc522b1e776d8b89b585e4d2c2a73406ee0a53a5ff4498f3` | Retained rollback material. No active exact-old-runtime-path reference was found. |
| Instagram | Internal `instagram-post-watch/state` | 170,823 bytes, `5ce73249f6aeb8393a80140e4611468565d2fe96b5c476b5ff44cb5392f54864` | Retained rollback material. Instagram remains inactive. |
| Kelas Investasi GTW | `~/.hermes/state/kelas-investasi-gtw-watch.json` | 79 bytes, `95f2dfb70554f5b5ff155115b5e9d87fd2ca3e0d3528725b41a242927b8103d1` | Current Bursawatch GTW deliberately uses this compatibility state. Do not clean. |
| WhatsApp | `~/.hermes/state/whatsapp-channel-watch/` | 104,680 bytes, `c1dfeb8e655e1622a1c9fe3793852654ddfe3fe9dda2021f19a2b8e772ebb4dd` | Current inactive BRI WhatsApp wrapper retains this configured state. Do not clean or activate. |
| X Post Watch | Internal `x-post-watch/state` | 1,648,599 bytes, `3d9bb9cc4994b215f5b1523798c89d9990f2d31db21d77dfd2c83a89057d8744` | Retained rollback material. No active exact-old-runtime-path reference was found. |

The shared `telegram-resilience-polyclop.json` is Bursawatch-owned shared
control-plane state, not old-directory cleanup material. The retired SSF state
file remains separately retained and is not part of the active Swing Board.

## Active-reference proof

The snapshot inspected every active Hermes job, its Bursawatch wrapper, all
Bursawatch runtime files, all systemd units, and running processes while
excluding the audit process itself.

- No active Hermes scheduler record uses an old job name or old wrapper.
- No Bursawatch wrapper or Bursawatch runtime file references any exact old
  `~/.agents/skills/<old-name>` directory.
- No systemd unit references an old runtime name.
- No running process references an old runtime name.
- The active Board, Market News, GTW, and inactive WhatsApp wrapper
  intentionally retain legacy-named state paths. These are current
  compatibility state hosts, not references to old runtime directories.
- The inactive Instagram wrapper has a separately named OCR virtual
  environment under `~/.local/share/instagram-post-watch/`. It is not one of
  the retained runtime directories and must remain untouched while Instagram
  stays inactive.

This proves the old runtime directories are not in the active execution graph
at the audit snapshot. It does not authorize deleting their rollback material
or any shared compatibility state.
