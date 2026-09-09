FROM diygod/rsshub@sha256:b3789602a2c3cc136d6345bdb8c7e813df430564744ffad8aebc604aea451761

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*
