# Discord Delivery Owner host deployment

These files describe a reviewed VPS target. They are not authorization to copy
files, create credentials, migrate live operation state, install a unit, start
the service, or expose a port. Obtain explicit current-chat approval before a
first bootstrap or later release operation.

## Target layout

```text
/home/praya/.hermes/
  bursawatch-discord-delivery.env                     mode 0600
  secrets/
    bursawatch-discord-delivery-bot-token             mode 0600
    bursawatch-discord-delivery-client-token          mode 0600
    bursawatch-discord-delivery-emoji-token           mode 0600 when enabled
    bursawatch-discord-delivery-admin-token           mode 0600
  bursawatch-discord-delivery/
    bin/
    requirements.txt
    venv/
  state/
    bursawatch-discord-delivery.sqlite3               mode 0600
    bursawatch-discord-delivery-media/                 mode 0700
```

The service environment holds client and admin API token values, an optional
`DISCORD_DELIVERY_EMOJI_TOKEN`, and paths for the bot token, SQLite database,
and media directory. The client-token file matches `DISCORD_DELIVERY_API_TOKEN`;
the admin-token file matches `DISCORD_DELIVERY_ADMIN_TOKEN`; when enabled, the
emoji-token file matches `DISCORD_DELIVERY_EMOJI_TOKEN`. Keep all credentials
distinct. Without the emoji token, the service stays available and rejects
emoji creation. Do not print or store any token value in this repository.

The service listens on `127.0.0.1:9120`. Do not add an Nginx route, tunnel,
public bind address, DNS name, or firewall allowance. The HTTP API is for local
watchers and operators on the VPS only.

## First host bootstrap gate

The first installation is a separate manual host operation. Before it, compare
each approved source and systemd file with the VPS target and confirm the
current service/release state. Then, only within the approved scope:

1. Create the dedicated service directory and Python virtual environment;
   install the pinned `requirements.txt` into that environment.
2. Create a private dedicated environment file from `env.example`. Supply
   distinct API/admin tokens, the optional distinct emoji token, and the
   reviewed token, database, and media paths.
3. Install each token file as a regular mode-0600 file owned by `praya`. The
   service validates the bot-token file and never expects client callers to
   receive it.
4. Install
   `deployment/systemd/bursawatch-discord-delivery.service`, run
   `systemctl daemon-reload`, and enable/start it only after the approved
   bootstrap is ready.
5. Verify `systemctl is-active` and
   `curl --noproxy '*' http://127.0.0.1:9120/healthz` on the VPS. Health proves
   the local service responds, not that Discord delivery succeeded.

The SQLite schema is initialized by the service when it opens the database;
there is no standalone schema-migration command. Moving existing source
outboxes into this ledger is a separate cutover: pause each source writer and
watchdog, snapshot and hash the local source state, inspect its package's
payload-free plan, then apply only after separate approval. Never copy production
state into this worktree or treat a service release as a source-state migration.

## Read-only inspection and repeat releases

After the bootstrap has been reviewed, inspect with:

```bash
./service-bursawatch-discord-delivery/deploy.sh plan
./service-bursawatch-discord-delivery/deploy.sh status
./service-bursawatch-discord-delivery/deploy.sh verify
```

`plan` runs an rsync dry run, `status` checks the existing systemd unit and
loopback health endpoint, and `verify` combines both checks. These commands do
not sync files, migrate state, install dependencies, restart the service, or
post a Discord message.

For a later code release, first inspect the exact diff and target. The mutating
commands require a clean commit published to `origin` and the explicit flag;
they also require current-chat deployment approval:

```bash
./service-bursawatch-discord-delivery/deploy.sh release --apply
```

`sync --apply` synchronizes only `bin/` and `requirements.txt` and updates the
already-created virtual environment. `restart --apply` restarts only the
already installed unit. `release --apply` combines those operations and checks
loopback health. None changes the environment file, tokens, unit file,
firewall/network exposure, scheduler, source outboxes, or Board state. The
release manifest marks the whole service package manual, so the automatic
release timer cannot install or update it.
