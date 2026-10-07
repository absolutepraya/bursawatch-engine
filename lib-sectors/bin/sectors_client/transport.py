"""Bounded standard-library HTTPS transport with no redirect or implicit retry."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .models import (ORIGIN, AuthenticationFailure, AllowanceExhausted,
                     Throttled, TransportFailure, UncertainOutcome, ValidationError)


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def __init__(self, config, *, opener=None):
        self.config = config
        self.opener = opener if opener is not None else build_opener(_RefuseRedirect())

    def get(self, identity):
        if not self.config.api_key:
            raise ValidationError('provider key required for network mode')
        request = Request(identity.url, headers={
            'Authorization': self.config.api_key,
            'User-Agent': self.config.user_agent,
            'Accept': 'application/json',
        })
        open_ = self.opener.open if hasattr(self.opener, 'open') else self.opener
        try:
            try:
                response = open_(request, timeout=self.config.timeout_seconds)
                with response:
                    if response.geturl() != identity.url:
                        raise TransportFailure('provider redirect refused')
                    status = response.status
                    raw = response.read(self.config.max_bytes + 1)
                    if len(raw) > self.config.max_bytes:
                        raise TransportFailure('provider response exceeds size limit')
                    if status != 200:
                        self._status(status, response.headers, raw)
            except HTTPError as error:
                try:
                    raw = error.read(self.config.max_bytes + 1)
                    self._status(error.code, error.headers, raw)
                finally:
                    error.close()
        except (TransportFailure, AuthenticationFailure, AllowanceExhausted, Throttled):
            raise
        except Exception:
            raise UncertainOutcome('provider request billing outcome is uncertain') from None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise TransportFailure('provider returned invalid JSON') from None
        if not isinstance(result, (dict, list)):
            raise TransportFailure('provider returned invalid JSON shape')
        return result

    def _status(self, status, headers, raw):
        if status in (401, 403):
            raise AuthenticationFailure('provider authentication denied') from None
        if status == 402:
            raise AllowanceExhausted('provider allowance exhausted') from None
        if status == 429:
            try:
                payload = json.loads(raw)
                code = payload.get('code') if isinstance(payload, dict) else None
            except (ValueError, UnicodeError):
                code = None
            if code in ('insufficient_credits', 'credits_exhausted', 'quota_exceeded'):
                raise AllowanceExhausted('provider allowance exhausted') from None
            hint = headers.get('Retry-After')
            retry_after = None
            if hint is not None:
                try:
                    retry_after = max(0, int(hint))
                except (ValueError, TypeError):
                    try:
                        retry_after = max(0, (parsedate_to_datetime(hint) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        pass
            if retry_after is not None and retry_after > 365 * 86400:
                # Unrepresentable/unreasonable hints stay unresolved, never shorten
                # a provider cooldown to enable another request.
                retry_after = None
            raise Throttled(retry_after) from None
        raise TransportFailure('provider HTTP request rejected') from None
