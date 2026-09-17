import test from 'node:test';
import assert from 'node:assert/strict';
import {
  enqueueChannelEvent,
  configuredNewsletterJids,
  followNewsletter,
  normalizeChannelMessage,
  normalizeNewsletterJid,
} from '../bin/channel_sink.mjs';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const base = (message, overrides = {}) => ({
  key: { remoteJid: '12345@newsletter', id: 'ABC-001' },
  messageTimestamp: 1756000000,
  message,
  ...overrides,
});

test('normalizes text Channel posts and rejects non-Channels', () => {
  const result = normalizeChannelMessage({msg: base({conversation: 'BBCA mencatat laba bersih naik'})});
  assert.deepEqual(result, {
    channel_jid: '12345@newsletter',
    message_id: 'ABC-001',
    published_at: 1756000000,
    text: 'BBCA mencatat laba bersih naik',
    links: [],
    media: [],
    received_at: result.received_at,
  });
  assert.equal(normalizeChannelMessage({msg: base({conversation: 'no'}, {key: {remoteJid: '1@g.us', id: 'x'}})}), null);
});

test('normalizes captions and supported media without copying raw bytes', () => {
  const result = normalizeChannelMessage({
    msg: base({imageMessage: {caption: 'Laporan lengkap', mimetype: 'image/jpeg', jpegThumbnail: {type: 'Buffer', data: [1, 2]}}}),
    mediaPath: '/private/media/image.jpg',
  });
  assert.deepEqual(result.media, [{kind: 'image', mime: 'image/jpeg', path: '/private/media/image.jpg'}]);
  assert.equal(result.text, 'Laporan lengkap');
  assert.equal(JSON.stringify(result).includes('jpegThumbnail'), false);
});

test('ignores unsupported media and empty malformed timestamps', () => {
  assert.equal(normalizeChannelMessage({msg: base({audioMessage: {mimetype: 'audio/ogg'}})}), null);
  assert.equal(normalizeChannelMessage({msg: base({conversation: 'text'}, {messageTimestamp: 0})}), null);
});

test('follows a Channel and subscribes to live updates through the existing socket', async () => {
  const calls = [];
  const result = await followNewsletter({
    sock: {
      async newsletterFollow(jid) { calls.push(['follow', jid]); },
      async subscribeNewsletterUpdates(jid) { calls.push(['subscribe', jid]); return {duration: '86400'}; },
    },
    jid: '12345@newsletter',
  });
  assert.deepEqual(calls, [
    ['follow', '12345@newsletter'],
    ['subscribe', '12345@newsletter'],
  ]);
  assert.deepEqual(result, {
    channel_jid: '12345@newsletter',
    followed: true,
    subscribed: true,
    duration: '86400',
  });
});

test('rejects non-Channel follow targets', () => {
  assert.throws(() => normalizeNewsletterJid('12345@g.us'), /Invalid newsletter JID/);
});

test('selects unique enabled Channel profiles from watcher configuration', () => {
  assert.deepEqual(configuredNewsletterJids({
    profiles: [
      {enabled: true, channel_jid: '12345@newsletter'},
      {enabled: false, channel_jid: '67890@newsletter'},
      {enabled: true, channel_jid: '12345@newsletter'},
      {enabled: true, channel_jid: 'not-a-channel'},
    ],
  }), ['12345@newsletter']);
});

test('writes one durable event and deduplicates it', async () => {
  const queueDir = await mkdtemp(path.join(tmpdir(), 'wa-channel-'));
  const payload = normalizeChannelMessage({msg: base({conversation: 'BBCA mencatat laba bersih naik'})});
  assert.equal(enqueueChannelEvent(payload, queueDir), true);
  assert.equal(enqueueChannelEvent(payload, queueDir), false);
  const names = await (await import('node:fs/promises')).readdir(queueDir);
  assert.equal(names.length, 1);
  const stored = JSON.parse(await readFile(path.join(queueDir, names[0]), 'utf8'));
  assert.equal(stored.schema_version, 1);
  assert.equal(stored.event_key, '12345@newsletter:ABC-001');
  assert.equal(stored.channel_jid, '12345@newsletter');
  assert.deepEqual(stored.links, []);
  assert.equal(typeof stored.received_at, 'string');
});

test('deduplicates a redelivered source event even when receipt time changes', async () => {
  const queueDir = await mkdtemp(path.join(tmpdir(), 'wa-channel-'));
  const first = normalizeChannelMessage({msg: base({conversation: 'BBCA mencatat laba bersih naik'})});
  const second = {...first, received_at: '2026-09-10T10:11:12.000Z'};
  assert.equal(enqueueChannelEvent(first, queueDir), true);
  assert.equal(enqueueChannelEvent(second, queueDir), false);
});
