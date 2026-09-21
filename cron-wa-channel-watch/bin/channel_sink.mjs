const NEWSLETTER_SUFFIX = '@newsletter';
const SUPPORTED_MEDIA = new Set(['image', 'video']);
const MESSAGE_ID_RE = /^[A-Za-z0-9._:-]{1,256}$/;
const NEWSLETTER_JID_RE = /^[^@\s]+@newsletter$/;
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync, chmodSync, unlinkSync } from 'node:fs';
import path from 'node:path';

const ARCHIVE_SCHEMA_VERSION = 1;
const ARCHIVE_PROFILE_ID_RE = /^[a-z0-9][a-z0-9_-]{1,63}$/;
const MAX_ARCHIVE_MEDIA_BYTES = 25 * 1024 * 1024;

function contentOf(msg) {
  let content = msg?.message || {};
  for (const wrapper of ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2', 'documentWithCaptionMessage']) {
    if (content?.[wrapper]?.message) content = content[wrapper].message;
  }
  return content;
}

function mediaDescriptor(kind, value, path) {
  return {
    kind,
    mime: typeof value?.mimetype === 'string' ? value.mimetype : null,
    ...(typeof path === 'string' && path ? { path } : {}),
  };
}

function linksFromText(text) {
  const found = [];
  for (const match of String(text || '').matchAll(/https?:\/\/[^\s<>"']+/gi)) {
    const candidate = match[0].replace(/[.,!?;:)]+$/g, '');
    try {
      const parsed = new URL(candidate);
      if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) continue;
    } catch {
      continue;
    }
    if (!found.includes(candidate)) found.push(candidate);
  }
  return found;
}

/**
 * Convert one Baileys message into the strict payload accepted by the
 * watcher's durable queue.
 * Return null for non-Channel or unsupported message types.
 */
export function normalizeChannelMessage({ msg, mediaPath = null } = {}) {
  const channelJid = String(msg?.key?.remoteJid || '');
  if (!channelJid.endsWith(NEWSLETTER_SUFFIX)) return null;
  const messageId = String(msg?.key?.id || '');
  if (!MESSAGE_ID_RE.test(messageId)) return null;
  const content = contentOf(msg);
  let text = '';
  let media = [];
  if (typeof content?.conversation === 'string') {
    text = content.conversation;
  } else if (typeof content?.extendedTextMessage?.text === 'string') {
    text = content.extendedTextMessage.text;
  } else if (content?.imageMessage) {
    text = typeof content.imageMessage.caption === 'string' ? content.imageMessage.caption : '';
    media = [mediaDescriptor('image', content.imageMessage, mediaPath)];
  } else if (content?.videoMessage) {
    text = typeof content.videoMessage.caption === 'string' ? content.videoMessage.caption : '';
    media = [mediaDescriptor('video', content.videoMessage, mediaPath)];
  } else {
    return null;
  }
  const timestamp = typeof msg?.messageTimestamp?.toNumber === 'function'
    ? msg.messageTimestamp.toNumber()
    : Number(msg?.messageTimestamp || 0);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null;
  return {
    channel_jid: channelJid,
    message_id: messageId,
    published_at: timestamp,
    text,
    links: linksFromText(text),
    media,
    received_at: new Date().toISOString(),
  };
}

export function normalizeNewsletterJid(value) {
  const jid = String(value || '').trim();
  if (!NEWSLETTER_JID_RE.test(jid)) throw new Error('Invalid newsletter JID');
  return jid;
}

export function configuredNewsletterJids(value) {
  const profiles = Array.isArray(value?.profiles) ? value.profiles : [];
  const result = [];
  for (const profile of profiles) {
    if (profile?.enabled !== true) continue;
    try {
      const jid = normalizeNewsletterJid(profile.channel_jid);
      if (!result.includes(jid)) result.push(jid);
    } catch {}
  }
  return result;
}

export function enabledNewsletterProfile(value, newsletterJid) {
  const channelJid = normalizeNewsletterJid(newsletterJid);
  const profiles = Array.isArray(value?.profiles) ? value.profiles : [];
  for (const profile of profiles) {
    if (profile?.enabled !== true || typeof profile.id !== 'string' || !ARCHIVE_PROFILE_ID_RE.test(profile.id)) continue;
    try {
      if (normalizeNewsletterJid(profile.channel_jid) === channelJid) return profile;
    } catch {}
  }
  return null;
}

/**
 * Make the already-connected Baileys account follow one Channel and request
 * its live updates. This is an explicit onboarding operation, not part of
 * message intake, and never fetches or enqueues historical posts.
 */
export async function followNewsletter({ sock, jid } = {}) {
  const channelJid = normalizeNewsletterJid(jid);
  if (!sock || typeof sock.newsletterFollow !== 'function'
    || typeof sock.subscribeNewsletterUpdates !== 'function') {
    throw new Error('Newsletter controls are unavailable');
  }
  await sock.newsletterFollow(channelJid);
  const updates = await sock.subscribeNewsletterUpdates(channelJid);
  return {
    channel_jid: channelJid,
    followed: true,
    subscribed: true,
    duration: updates?.duration ?? null,
  };
}

export function enqueueChannelEvent(payload, queueDir) {
  if (!payload || typeof payload !== 'object') throw new TypeError('Channel payload is required');
  if (typeof queueDir !== 'string' || !queueDir) throw new TypeError('Channel queue directory is required');
  const eventKey = `${payload.channel_jid || ''}:${payload.message_id || ''}`;
  if (!payload.channel_jid?.endsWith(NEWSLETTER_SUFFIX) || !payload.message_id) {
    throw new Error('Channel payload identity is invalid');
  }
  const serialized = JSON.stringify({schema_version: 1, event_key: eventKey, ...payload});
  mkdirSync(queueDir, {recursive: true, mode: 0o700});
  chmodSync(queueDir, 0o700);
  const filename = `${createHash('sha256').update(eventKey).digest('hex')}.json`;
  const destination = path.join(queueDir, filename);
  if (existsSync(destination)) {
    try {
      const existing = JSON.parse(readFileSync(destination, 'utf8'));
      if (
        existing?.schema_version === 1 &&
        existing?.event_key === eventKey &&
        existing?.channel_jid === payload.channel_jid &&
        existing?.message_id === payload.message_id
      ) return false;
    } catch {}
    throw new Error('Channel event-key collision');
  }
  const temporary = path.join(queueDir, `.${filename}.${process.pid}.tmp`);
  try {
    writeFileSync(temporary, serialized, {encoding: 'utf8', mode: 0o600, flag: 'wx'});
    chmodSync(temporary, 0o600);
    renameSync(temporary, destination);
  } catch (error) {
    try { if (existsSync(temporary)) unlinkSync(temporary); } catch {}
    throw error;
  }
  return true;
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key])]));
  }
  return value;
}

function stableJson(value) {
  return `${JSON.stringify(stableValue(value))}\n`;
}

function archiveTimestamp(value, label) {
  let milliseconds;
  if (typeof value === 'number' && Number.isFinite(value)) {
    milliseconds = value > 10_000_000_000 ? value : value * 1000;
  } else if (typeof value === 'string') {
    milliseconds = Date.parse(value);
  } else {
    throw new Error(`Channel archive ${label} is invalid`);
  }
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) {
    throw new Error(`Channel archive ${label} is invalid`);
  }
  return new Date(milliseconds).toISOString();
}

function archiveDirectories(archiveDir, profileId, publishedAt) {
  if (typeof archiveDir !== 'string' || !path.isAbsolute(archiveDir)) {
    throw new Error('Channel archive directory must be absolute');
  }
  if (!ARCHIVE_PROFILE_ID_RE.test(profileId)) throw new Error('Channel archive profile ID is invalid');
  const date = new Date(publishedAt);
  const directory = path.join(
    archiveDir,
    profileId,
    String(date.getUTCFullYear()),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
  );
  mkdirSync(directory, {recursive: true, mode: 0o700});
  chmodSync(archiveDir, 0o700);
  chmodSync(directory, 0o700);
  return directory;
}

function safeRelativeMediaPath(archiveDir, digest) {
  const mediaDirectory = path.join(archiveDir, 'media');
  mkdirSync(mediaDirectory, {recursive: true, mode: 0o700});
  chmodSync(mediaDirectory, 0o700);
  return {absolute: path.join(mediaDirectory, digest), relative: path.posix.join('media', digest)};
}

function copyStagedMedia(media, {archiveDir, stagingRoot}) {
  if (typeof media?.path !== 'string' || !media.path) {
    return {capture_status: 'unavailable', archive_path: null, sha256: null, bytes: null};
  }
  if (typeof stagingRoot !== 'string' || !path.isAbsolute(stagingRoot)) {
    throw new Error('Channel media staging root must be absolute');
  }
  if (!path.isAbsolute(media.path)) throw new Error('Channel media path is outside staging root');
  const descriptor = lstatSync(media.path);
  if (descriptor.isSymbolicLink()) throw new Error('Channel media path must not be a symlink');
  const staging = realpathSync(stagingRoot);
  const source = realpathSync(media.path);
  const relative = path.relative(staging, source);
  if (!relative || relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) {
    throw new Error('Channel media path is outside staging root');
  }
  const sourceStats = statSync(source);
  if (!sourceStats.isFile()) throw new Error('Channel media path must be a regular file');
  if (sourceStats.size > MAX_ARCHIVE_MEDIA_BYTES) throw new Error('Channel media exceeds archive size limit');
  const bytes = readFileSync(source);
  const digest = createHash('sha256').update(bytes).digest('hex');
  const destination = safeRelativeMediaPath(archiveDir, digest);
  if (existsSync(destination.absolute)) {
    const existingDigest = createHash('sha256').update(readFileSync(destination.absolute)).digest('hex');
    if (existingDigest !== digest) throw new Error('Channel archive media collision');
  } else {
    const temporary = `${destination.absolute}.${process.pid}.tmp`;
    try {
      copyFileSync(source, temporary, 0);
      chmodSync(temporary, 0o600);
      renameSync(temporary, destination.absolute);
      chmodSync(destination.absolute, 0o600);
    } catch (error) {
      try { if (existsSync(temporary)) unlinkSync(temporary); } catch {}
      throw error;
    }
  }
  return {capture_status: 'captured', archive_path: destination.relative, sha256: digest, bytes: sourceStats.size};
}

function archiveMedia(payload, options) {
  if (!Array.isArray(payload.media)) throw new Error('Channel archive media is invalid');
  return payload.media.map((media, index) => {
    if (!SUPPORTED_MEDIA.has(media?.kind)) throw new Error('Channel archive media is invalid');
    const descriptor = {
      kind: media.kind,
      index,
      mime: typeof media.mime === 'string' ? media.mime : null,
    };
    try {
      return {...descriptor, ...copyStagedMedia(media, options)};
    } catch (error) {
      if (/staging root|symlink|size limit|regular file/.test(String(error?.message || error))) throw error;
      return {...descriptor, capture_status: 'unavailable', archive_path: null, sha256: null, bytes: null};
    }
  });
}

function archiveRecord(payload, {archiveDir, profileId, stagingRoot}) {
  if (!payload || typeof payload !== 'object') throw new TypeError('Channel payload is required');
  const channelJid = String(payload.channel_jid || '');
  const messageId = String(payload.message_id || '');
  if (!channelJid.endsWith(NEWSLETTER_SUFFIX) || !messageId) {
    throw new Error('Channel payload identity is invalid');
  }
  if (typeof payload.text !== 'string' || !Array.isArray(payload.links) || !payload.links.every(link => typeof link === 'string')) {
    throw new Error('Channel archive source content is invalid');
  }
  const publishedAt = archiveTimestamp(payload.published_at, 'published_at');
  const receivedAt = archiveTimestamp(payload.received_at, 'received_at');
  const eventKey = `${channelJid}:${messageId}`;
  const record = {
    schema_version: ARCHIVE_SCHEMA_VERSION,
    event_key: eventKey,
    profile_id: profileId,
    channel_jid: channelJid,
    message_id: messageId,
    published_at: publishedAt,
    received_at: receivedAt,
    text: payload.text,
    links: payload.links,
    media: archiveMedia(payload, {archiveDir, stagingRoot}),
    config_revision: null,
  };
  const checksum = createHash('sha256').update(stableJson(record), 'utf8').digest('hex');
  return {...record, checksum};
}

function sameArchivedSource(existing, record) {
  const existingMedia = existing?.media;
  const recordMedia = record.media;
  const sameMediaDescriptors = Array.isArray(existingMedia)
    && Array.isArray(recordMedia)
    && existingMedia.length === recordMedia.length
    && existingMedia.every((media, index) => (
      media?.kind === recordMedia[index]?.kind
      && media?.index === recordMedia[index]?.index
      && media?.mime === recordMedia[index]?.mime
    ));
  return existing?.schema_version === ARCHIVE_SCHEMA_VERSION
    && existing?.event_key === record.event_key
    && existing?.profile_id === record.profile_id
    && existing?.channel_jid === record.channel_jid
    && existing?.message_id === record.message_id
    && existing?.published_at === record.published_at
    && existing?.text === record.text
    && JSON.stringify(existing?.links) === JSON.stringify(record.links)
    && sameMediaDescriptors;
}

function capturedMediaUpgrade(existing, record) {
  if (!sameArchivedSource(existing, record)) return null;
  const upgraded = JSON.parse(JSON.stringify(existing));
  let changed = false;
  for (let index = 0; index < record.media.length; index += 1) {
    if (existing.media[index]?.capture_status !== 'captured'
      && record.media[index]?.capture_status === 'captured') {
      upgraded.media[index] = record.media[index];
      changed = true;
    }
  }
  if (!changed) return null;
  delete upgraded.checksum;
  upgraded.checksum = createHash('sha256').update(stableJson(upgraded), 'utf8').digest('hex');
  return upgraded;
}

function replaceArchivedRecord(destination, record) {
  const temporary = `${destination}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, stableJson(record), {encoding: 'utf8', mode: 0o600, flag: 'wx'});
    chmodSync(temporary, 0o600);
    renameSync(temporary, destination);
    chmodSync(destination, 0o600);
  } catch (error) {
    try { if (existsSync(temporary)) unlinkSync(temporary); } catch {}
    throw error;
  }
}

/**
 * Persist one immutable source record before queueing a Channel event.
 * Source-media paths never enter the archive record.
 */
export function archiveChannelEvent(payload, {archiveDir, profileId, stagingRoot} = {}) {
  const record = archiveRecord(payload, {archiveDir, profileId, stagingRoot});
  const directory = archiveDirectories(archiveDir, profileId, record.published_at);
  const filename = `${createHash('sha256').update(record.event_key).digest('hex')}.json`;
  const destination = path.join(directory, filename);
  if (existsSync(destination)) {
    try {
      const existing = JSON.parse(readFileSync(destination, 'utf8'));
      if (sameArchivedSource(existing, record)) {
        const upgraded = capturedMediaUpgrade(existing, record);
        if (upgraded) replaceArchivedRecord(destination, upgraded);
        return false;
      }
    } catch {}
    throw new Error('Channel archive event-key collision');
  }
  const temporary = path.join(directory, `.${filename}.${process.pid}.tmp`);
  try {
    writeFileSync(temporary, stableJson(record), {encoding: 'utf8', mode: 0o600, flag: 'wx'});
    chmodSync(temporary, 0o600);
    renameSync(temporary, destination);
    chmodSync(destination, 0o600);
  } catch (error) {
    try { if (existsSync(temporary)) unlinkSync(temporary); } catch {}
    throw error;
  }
  return true;
}

export { NEWSLETTER_SUFFIX, SUPPORTED_MEDIA };
