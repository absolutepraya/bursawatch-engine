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
      items: [{ id: 'publication-1' }],
      user: { id: '123', username: 'investart_id', full_name: 'Investart' },
    }),
    'investart_id',
  );

  assert.deepEqual(JSON.parse(body), {
    data: {
      user: { id: '123', username: 'investart_id', full_name: 'Investart' },
    },
  });
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
    printf '%b' '{"items":[{"id":"publication-1"}],"user":{"id":"123","username":"investart_id","full_name":"Investart"}}\n__RSSHUB_INSTAGRAM_STATUS__200'
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
    assert.deepEqual(await response.json(), {
      data: {
        user: { id: '123', username: 'investart_id', full_name: 'Investart' },
      },
    });
  } finally {
    if (previousPath === undefined) delete process.env.PATH;
    else process.env.PATH = previousPath;
    if (previousProxy === undefined) delete process.env.PROXY_URI;
    else process.env.PROXY_URI = previousProxy;
    await rm(tempDir, { recursive: true, force: true });
  }
});
