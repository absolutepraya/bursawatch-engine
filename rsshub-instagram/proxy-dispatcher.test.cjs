'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { chmod, mkdtemp, rm, writeFile } = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const dispatcher = require('./proxy-dispatcher.cjs');

test('matches only Instagram web profile info requests with safe handles', () => {
  assert.equal(
    dispatcher.profileInfoUsername('https://www.instagram.com/api/v1/users/web_profile_info/?username=investart_id'),
    'investart_id',
  );
  assert.equal(
    dispatcher.profileInfoUsername('https://www.instagram.com/api/v1/users/web_profile_info/?username=avenirresearch.id'),
    'avenirresearch.id',
  );
  assert.equal(
    dispatcher.profileInfoUsername('https://www.instagram.com/api/v1/feed/user/sectorsapp/username/?count=30'),
    null,
  );
  assert.equal(
    dispatcher.profileInfoUsername('https://example.com/api/v1/users/web_profile_info/?username=investart_id'),
    null,
  );
  assert.equal(
    dispatcher.profileInfoUsername('https://www.instagram.com/api/v1/users/web_profile_info/?username=bad%2Fhandle'),
    null,
  );
});

test('recognizes only the known deleted business-profile schema failure', () => {
  assert.equal(
    dispatcher.isBusinessProfileSchemaFailure(
      400,
      JSON.stringify({ message: dispatcher.businessSchemaError, status: 'fail' }),
    ),
    true,
  );
  assert.equal(dispatcher.isBusinessProfileSchemaFailure(403, dispatcher.businessSchemaError), false);
  assert.equal(dispatcher.isBusinessProfileSchemaFailure(400, 'different provider failure'), false);
});

test('synthesizes the RSSHub profile shape from a valid feed response', () => {
  const body = dispatcher.profileInfoFallbackBody(
    JSON.stringify({
      items: [{
        pk: 'publication-1',
        code: 'CODE1',
        product_type: 'feed',
        media_type: 1,
        taken_at: 1_724_483_200,
        caption: { text: 'A market caption' },
        image_versions2: { candidates: [{ url: 'https://cdn.example/one.jpg', width: 100, height: 120 }] },
      }, {
        pk: 'publication-2',
        code: 'CODE2',
        product_type: 'carousel_container',
        media_type: 8,
        taken_at: 1_724_483_201,
        caption: { text: 'A carousel caption' },
        image_versions2: { candidates: [{ url: 'https://cdn.example/two.jpg', width: 100, height: 120 }] },
        carousel_media: [{
          pk: 'publication-2-1',
          media_type: 1,
          image_versions2: { candidates: [{ url: 'https://cdn.example/two-a.jpg', width: 100, height: 120 }] },
        }, {
          pk: 'publication-2-2',
          media_type: 2,
          image_versions2: { candidates: [{ url: 'https://cdn.example/two-b.jpg', width: 100, height: 120 }] },
          video_versions: [{ url: 'https://cdn.example/two-b.mp4' }],
        }],
      }, {
        pk: 'publication-3',
        code: 'CODE3',
        product_type: 'clips',
        media_type: 2,
        taken_at: 1_724_483_202,
        caption: { text: 'A reel caption' },
        image_versions2: { candidates: [{ url: 'https://cdn.example/three.jpg', width: 100, height: 120 }] },
        video_versions: [{ url: 'https://cdn.example/three.mp4' }],
      }],
      user: { id: '123', username: 'investart_id', full_name: 'Investart' },
    }),
    'investart_id',
  );

  const user = JSON.parse(body).data.user;
  assert.equal(user.username, 'investart_id');
  assert.deepEqual(user.edge_felix_video_timeline, { edges: [] });
  assert.equal(user.edge_owner_to_timeline_media.edges.length, 3);
  assert.equal(user.edge_owner_to_timeline_media.edges[0].node.__typename, 'GraphImage');
  assert.equal(user.edge_owner_to_timeline_media.edges[0].node.edge_media_to_caption.edges[0].node.text, 'A market caption');
  assert.equal(user.edge_owner_to_timeline_media.edges[1].node.__typename, 'GraphSidecar');
  assert.deepEqual(
    user.edge_owner_to_timeline_media.edges[1].node.edge_sidecar_to_children.edges.map(({ node }) => node.__typename),
    ['GraphImage', 'GraphVideo'],
  );
  assert.equal(user.edge_owner_to_timeline_media.edges[2].node.__typename, 'GraphVideo');
  assert.equal(user.edge_owner_to_timeline_media.edges[2].node.video_url, 'https://cdn.example/three.mp4');
});

test('does not synthesize metadata from an incomplete feed response', () => {
  assert.equal(dispatcher.profileInfoFallbackBody(JSON.stringify({ items: [] }), 'investart_id'), null);
  assert.equal(dispatcher.profileInfoFallbackBody(JSON.stringify({ user: { username: 'investart_id' } }), 'investart_id'), null);
});

test('recovers the profile request through the working feed request', async () => {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), 'rsshub-dispatcher-test-'));
  const fakeCurl = path.join(tempDir, 'curl');
  await writeFile(fakeCurl, `#!/bin/sh
url=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--url" ]; then
    url="$2"
    shift 2
  else
    shift
  fi
done
case "$url" in
  */api/v1/users/web_profile_info/*)
    printf '%b' '{"message":"${dispatcher.businessSchemaError}","status":"fail"}\n__RSSHUB_INSTAGRAM_STATUS__400'
    ;;
  */api/v1/feed/user/investart_id/username/*)
    printf '%b' '{"items":[{"pk":"publication-1","code":"CODE1","product_type":"feed","media_type":1,"taken_at":1724483200,"caption":{"text":"A market caption"},"image_versions2":{"candidates":[{"url":"https://cdn.example/one.jpg","width":100,"height":120}]}}],"user":{"id":"123","username":"investart_id","full_name":"Investart"}}\n__RSSHUB_INSTAGRAM_STATUS__200'
    ;;
  *)
    printf '%b' '{}\n__RSSHUB_INSTAGRAM_STATUS__404'
    ;;
esac
`, { encoding: 'utf8', mode: 0o700 });
  await chmod(fakeCurl, 0o700);

  const previousPath = process.env.PATH;
  const previousProxy = process.env.PROXY_URI;
  process.env.PATH = `${tempDir}:${previousPath || ''}`;
  process.env.PROXY_URI = 'http://proxy.invalid';
  try {
    const response = await globalThis.fetch(
      'https://www.instagram.com/api/v1/users/web_profile_info/?username=investart_id',
      { headers: { cookie: 'csrftoken=test', 'x-csrftoken': 'test' } },
    );
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.data.user.username, 'investart_id');
    assert.equal(payload.data.user.edge_owner_to_timeline_media.edges[0].node.__typename, 'GraphImage');
  } finally {
    if (previousPath === undefined) delete process.env.PATH;
    else process.env.PATH = previousPath;
    if (previousProxy === undefined) delete process.env.PROXY_URI;
    else process.env.PROXY_URI = previousProxy;
    await rm(tempDir, { recursive: true, force: true });
  }
});
