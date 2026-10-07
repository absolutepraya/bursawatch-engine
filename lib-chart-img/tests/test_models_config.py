from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO

import pytest
from PIL import Image

from chart_img_client import (AsOfVerification, ChartImgConfig, ChartImgError,
                              RenderRequest, load_config, validate_image)

CUTOFF = datetime(2026, 10, 5, 0, 30, tzinfo=timezone.utc)


def request(**kw):
    defaults = dict(profile_revision='profile-v1', layout_revision='layout-v1',
                    symbol='IDX:COMPOSITE', interval='1D', time_range='3M',
                    cutoff=CUTOFF, layout_id='public123')
    defaults.update(kw)
    return RenderRequest(**defaults)


def png(width=800, height=600, fmt='PNG'):
    out = BytesIO()
    Image.new('RGB', (width, height), 'white').save(out, format=fmt)
    return out.getvalue()


def test_complete_identity_changes_with_each_render_input():
    original = request()
    for kw in ({'profile_revision': 'profile-v2'}, {'layout_revision': 'layout-v2'},
               {'symbol': 'IDX:BBCA'}, {'interval': '1W'}, {'time_range': '6M'},
               {'cutoff': CUTOFF.replace(day=6)}, {'layout_id': 'different'},
               {'width': 900}, {'layout_id': None, 'options': {'theme': 'dark'}}):
        assert replace(original, **kw).identity != original.identity
    options = {'studies': [{'name': 'RSI', 'input': {'length': 14}}]}
    req = request(layout_id=None, options=options)
    before = req.identity
    options['studies'][0]['input']['length'] = 99
    assert req.identity == before
    assert req.payload['symbol'] == 'IDX:COMPOSITE'
    assert 'cutoff' not in req.payload  # Provider date control is not invented.
    assert 'range' not in original.payload  # Shared layouts have no verified range control.
    assert replace(original, layout_id=None).payload['range'] == '3M'


@pytest.mark.parametrize('kw', [{'profile_revision': ''}, {'layout_revision': ''},
                              {'symbol': 'https://evil'}, {'layout_id': '../secret'},
                              {'interval': 'invalid'}, {'time_range': 'tomorrow'},
                              {'cutoff': CUTOFF.replace(tzinfo=None)},
                              {'width': 0}, {'options': {'symbol': 'override'}},
                              {'options': {'api_key': 'secret'}},
                              {'options': {'cookie': 'secret'}}])
def test_invalid_or_auth_overriding_requests_fail_without_echoing_values(kw):
    with pytest.raises(ChartImgError) as caught:
        replace(request(), **kw)
    assert 'secret' not in str(caught.value)
    assert 'https://evil' not in str(caught.value)


def test_config_reads_only_explicit_documented_package_key(tmp_path):
    local = tmp_path / '.env'
    local.write_text('CHART_IMG_API_KEY="test-private"\nCHART_IMG_LAYOUT_ID=ignored\nOTHER=$(touch dangerous)\n')
    local.chmod(0o600)
    config = load_config(local)
    assert config.api_key == 'test-private'
    assert 'test-private' not in repr(config)
    assert not (tmp_path / 'dangerous').exists()
    assert not hasattr(config, 'layout_id')
    with pytest.raises(ChartImgError):
        ChartImgConfig(api_key='bad\r\nheader')


def test_decoded_image_returns_digest_dimensions_and_no_temporal_claim():
    artifact = validate_image(png(), 'image/png', request(), CUTOFF)
    assert (artifact.width, artifact.height, artifact.format) == (800, 600, 'PNG')
    assert len(artifact.sha256) == 64
    assert artifact.verification is None
    proof = AsOfVerification(image_sha256=artifact.sha256, request_identity=artifact.request.identity, last_bar_date='2026-10-02',
                             verified_at=CUTOFF, method='fixture-inspection',
                             evidence_ref='fixture:ihsg-1', time_range='3M')
    assert artifact.with_verification(proof).verification == proof
    with pytest.raises(ChartImgError):
        artifact.with_verification(replace(proof, image_sha256='0' * 64))
    with pytest.raises(ChartImgError):
        artifact.with_verification(replace(proof, last_bar_date='2026-10-06'))
    with pytest.raises(ChartImgError):
        artifact.with_verification(replace(proof, time_range='6M'))


@pytest.mark.parametrize('body,mime', [(b'<html>error</html>', 'image/png'),
                                    (png(), 'text/html'), (png(fmt='JPEG'), 'image/png'),
                                    (png(640, 480), 'image/png'),
                                    (png()[:60], 'image/png')],
                         ids=['html', 'wrong-mime', 'format-mismatch', 'dimensions', 'truncated'])
def test_invalid_image_bodies_are_rejected(body, mime):
    with pytest.raises(ChartImgError) as caught:
        validate_image(body, mime, request(), CUTOFF)
    assert caught.value.code == 'invalid_image'


def test_image_byte_limit_rejects_before_decoding():
    with pytest.raises(ChartImgError):
        validate_image(png(), 'image/png', request(), CUTOFF, max_bytes=100)


def test_credential_loader_rejects_public_or_oversized_file(tmp_path):
    path = tmp_path / '.env'
    path.write_text('CHART_IMG_API_KEY=test-private\n')
    path.chmod(0o644)
    with pytest.raises(ChartImgError):
        load_config(path)
    path.chmod(0o600)
    path.write_text('CHART_IMG_API_KEY=test-private\n' + 'x' * 100_000)
    with pytest.raises(ChartImgError):
        load_config(path)


def test_verification_is_bound_to_full_request_as_well_as_image_digest():
    original = validate_image(png(), 'image/png', request(), CUTOFF)
    changed = validate_image(png(), 'image/png', replace(request(), layout_revision='changed'), CUTOFF)
    proof = AsOfVerification(image_sha256=original.sha256, request_identity=original.request.identity,
                             last_bar_date='2026-10-02', verified_at=CUTOFF,
                             method='controlled-fixture', evidence_ref='fixture:1', time_range='3M')
    assert original.with_verification(proof).verification == proof
    with pytest.raises(ChartImgError):
        changed.with_verification(proof)


def test_malformed_mime_is_a_safe_image_error():
    with pytest.raises(ChartImgError) as caught:
        validate_image(png(), None, request(), CUTOFF)
    assert caught.value.code == 'invalid_image'


def test_shared_layout_rejects_unsupported_study_and_style_overrides():
    with pytest.raises(ChartImgError):
        request(options={'studies': [{'name': 'RSI'}]})
    with pytest.raises(ChartImgError):
        request(options={'theme': 'dark'})


def test_advanced_profile_is_copied_and_validates_presentation_fields():
    for options in ({'theme': 'secret-invalid'}, {'studies': 'invalid'}, {'zoom': 'invalid'}):
        with pytest.raises(ChartImgError):
            request(layout_id=None, options=options)
