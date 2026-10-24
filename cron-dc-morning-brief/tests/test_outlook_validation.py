"""Source consistency is testable without assembling a publication."""
from copy import deepcopy
import subprocess
import sys
from pathlib import Path

import pytest


def scenario():
    base = dict(evidence_id='base', publisher_id='Phintraco',
                excerpt='Jika likuiditas pulih, IHSG menguat. Jika tekanan naik, pandangan berubah.',
                source_url='https://example.test/base', published_at='2026-10-04T09:00:00+00:00')
    opposing = {**base, 'evidence_id': 'opposing', 'publisher_id': 'Tuntun',
                'excerpt': 'IHSG tidak bebas tekanan global.', 'source_url': 'https://example.test/caution'}
    return dict(assessment='model_assigned_source_roles', base_case=base, supporting=[],
                opposing=[opposing], change_conditions=[base],
                pulse=dict(mode='collected_sources', optimistic=[base], cautious=[opposing]),
                limitations=['Bukti berlawanan tersedia; arah sesi tidak dipastikan.'])


def test_validation_import_does_not_load_formatting_or_rendering():
    root = Path(__file__).resolve().parents[1] / 'bin'
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from morning_brief.outlook_validation import validate_scenario
assert 'morning_brief.formatting' not in sys.modules
assert 'morning_brief.rendering' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script, str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('field,value', [
    ('excerpt', 'Different full source context.'),
    ('publisher_id', 'Another publisher'),
    ('source_url', 'https://example.test/another'),
    ('published_at', '2026-10-04T10:00:00+00:00'),
    ('evidence_hash', 'different-hash'),
])
def test_repeated_source_identity_requires_identical_context(core, field, value):
    value_scenario = scenario()
    value_scenario['supporting'] = [{**value_scenario['base_case'], field: value}]
    with pytest.raises(ValueError, match='inconsistent source context'):
        core('outlook_validation').validate_scenario(value_scenario)


@pytest.mark.parametrize('changes', [
    {'source_url': 'https://example.test/has space'},
    {'source_url': 'https://user:secret@example.test/private'},
    {'source_url': 'javascript:alert(1)'},
    {'published_at': '2026-10-04T09:00:00'},
    {'published_at': 'not-a-date'},
])
def test_provenance_is_checked_even_for_pulse_only_sources(core, changes):
    value = scenario()
    value['pulse']['optimistic'] = [{**value['base_case'], 'evidence_id': 'pulse-only', **changes}]
    with pytest.raises(ValueError):
        core('outlook_validation').validate_scenario(value)


def test_candidate_renderer_preserves_attribution_roles_and_exact_text(core):
    value = scenario()
    original = deepcopy(value)
    validated = core('outlook_validation').validate_scenario(value)
    text = core('formatting').format_scenario(validated)
    assert text == (
        '**Skenario IHSG** (asesmen model atas pandangan sumber)\n\n'
        '**Kasus dasar; Kondisi perubahan; narasi optimistis:** Menurut Phintraco · 04/10 16:00 WIB: '
        'Jika likuiditas pulih, IHSG menguat. Jika tekanan naik, pandangan berubah. '
        '(Sources: <https://example.test/base>)\n\n'
        '**Penentang; narasi hati-hati:** Menurut Tuntun · 04/10 16:00 WIB: '
        'IHSG tidak bebas tekanan global. (Sources: <https://example.test/caution>)\n\n'
        'Pendukung belum tersedia.\n\n'
        'Bukti berlawanan tersedia; arah sesi tidak dipastikan.\n\n'
        '**Narasi sumber terkumpul** (peran narasi dinilai model, bukan konsensus).'
    )
    assert value == original


def test_public_paragraph_does_not_render_the_candidate(core, monkeypatch):
    formatting = core('formatting')
    monkeypatch.setattr(formatting, 'format_scenario', lambda _: pytest.fail('candidate rendered during publication validation'))
    from test_formatting import inputs
    fields = inputs()
    fields['outlook']['scenario'] = scenario()
    texts, selected = formatting.format_brief(**fields, with_selection=True)
    assert 'Jika tekanan naik, pandangan berubah.' in texts[0]
    assert 'IHSG tidak bebas tekanan global.' in texts[0]
    assert 'Phintraco' not in texts[0] and 'Sources:' not in texts[0]
    assert selected['scenario']['pulse'] == dict(mode='absent', optimistic=[], cautious=[])


@pytest.mark.parametrize('invalid', ['pulse_mode', 'limitations'])
def test_non_public_scenario_fields_still_fail_validation(core, invalid):
    value = scenario()
    if invalid == 'pulse_mode': del value['pulse']['mode']
    else: value['limitations'] = [None]
    with pytest.raises((ValueError, KeyError, TypeError)):
        core('outlook_validation').validate_scenario(value)


def test_validation_preserves_selected_metadata_and_isolates_the_input(core):
    value = scenario()
    value['base_case'].update(version_ref='frozen-source-v1', evidence_hash='a'*64,
                              accepted_at='2026-10-04T09:05:00+00:00', origin_status='original')
    checked = core('outlook_validation').validate_scenario(value)
    assert checked.value == value
    value['base_case']['publisher_id'] = 'Changed after validation'
    assert checked.value['base_case']['publisher_id'] == 'Phintraco'
    assert checked.sources[0].context['version_ref'] == 'frozen-source-v1'


@pytest.mark.parametrize('publisher', [None, 42])
def test_claim_publisher_type_is_checked_before_rendering(core, publisher):
    payload = {'evidence': {'items': [dict(evidence_id='source', text='Factual source sentence.',
                source_url='https://example.test/source', publisher_id=publisher)]}}
    response = {'claims': [dict(evidence_id='source', excerpt='Factual source sentence.')], 'scenario': {}}
    with pytest.raises(ValueError, match='claim publisher required'):
        core('outlook_validation').validate_outlook(response, payload)
