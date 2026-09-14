const NEWSLETTER_SUFFIX = '@newsletter';
const SUPPORTED_MEDIA = new Set(['image', 'video']);
const MESSAGE_ID_RE = /^[A-Za-z0-9._:-]{1,256}$/;
const NEWSLETTER_JID_RE = /^[^@\s]+@newsletter$/;
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync, chmodSync, unlinkSync } from 'node:fs';
import path from 'node:path';

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

export { NEWSLETTER_SUFFIX, SUPPORTED_MEDIA };
