# Instagram RSSHub

This directory is the reviewed source for the dedicated RSSHub instance used
only by Hermes `instagram-post-watch`.

- Container: `rsshub-instagram`
- Local endpoint: `http://127.0.0.1:1201`
- Instagram route: `/instagram/2/user/<handle>`
- Instagram cookie and residential proxy: configured only in the VPS-local
  `.env` and passed only to this container
- `Dockerfile`: derives from a pinned RSSHub image and installs the CA bundle
  required by the dispatcher curl requests
- `proxy-dispatcher.cjs`: sends RSSHub's Instagram API requests through the
  configured proxy and recovers the narrow business-profile schema failure by
  reading the same profile's working feed response
- The health check validates both the CA bundle and the local RSSHub health
  endpoint. It does not treat an Instagram upstream outage as a container
  restart condition.

Do not use this instance for X or any other platform. Use the general
`~/rsshub` instance at `http://127.0.0.1:1200` for X and other RSSHub
watchers. The `rsshub-instagram` deploy script manages the dispatcher,
Dockerfile, and Compose file, then rebuilds only this container.

Do not put credentials, cookies, proxy values, or signed URLs in this README,
source control, or logs. Keep the VPS-local `.env` file mode `600`.
