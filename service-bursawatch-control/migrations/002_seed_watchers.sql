insert into bursawatch_watchers (watcher_id, display_name, validator_key)
values
    ('bursawatch-tg-market-news', 'Telegram Market News', 'bursawatch-tg-market-news'),
    ('bursawatch-tg-phintraco-swing', 'Telegram Phintraco Swing', 'bursawatch-tg-phintraco-swing'),
    ('bursawatch-tg-kelas-investasi-gtw', 'Telegram Kelas Investasi GTW', 'bursawatch-tg-kelas-investasi-gtw'),
    ('bursawatch-dc-swing-board', 'Discord Swing Board', 'bursawatch-dc-swing-board'),
    ('bursawatch-x-account-watch', 'X Account Watch', 'bursawatch-x-account-watch'),
    ('bursawatch-ig-account-watch', 'Instagram Account Watch', 'bursawatch-ig-account-watch'),
    ('bursawatch-wa-channel-watch', 'WhatsApp Channel Watch', 'bursawatch-wa-channel-watch')
on conflict (watcher_id) do update
    set display_name = excluded.display_name,
        validator_key = excluded.validator_key;
