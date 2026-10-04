import importlib
from dataclasses import asdict
import pytest


def api():
    return importlib.import_module("source_plan")


def field(source, text, label, value):
    start = source.index(text)
    return {"label":label,"value":value,"source_start":start,"source_end":start+len(text)}


def test_pwon_approved_synonyms():
    source = "PWON\nWatch on 270–282\nSupport utama 260\nTarget 1 288\nTarget 2 298"
    result = api().validate_source_plan_fields(source,[field(source,"Watch on 270–282","Entry","270–282"),field(source,"Support utama 260","Stop-loss","<260"),field(source,"Target 1 288","Target 1","288"),field(source,"Target 2 298","Target 2","298")])
    assert result.rejected_count == 0
    assert [(f.label,f.value) for f in api().source_plan_display(result.fields)] == [("Entry","270–282"),("Stop-loss","<260"),("Target 1","288"),("Target 2","298")]
    assert source[result.fields[1].source_start:result.fields[1].source_end] == "Support utama 260"


def test_missing_base_fields_do_not_create_extra_slots():
    assert [(f.label,f.value) for f in api().source_plan_display(())] == [("Entry","-"),("Stop-loss","-"),("Target 1","-")]


def test_tp2_before_tp1_and_missing_tp1():
    source = "TP2 380\nTP1 360"
    fields = api().validate_source_plan_fields(source,[field(source,"TP2 380","Target 2","380")]).fields
    assert [(f.label,f.value) for f in api().source_plan_display(fields)] == [("Entry","-"),("Stop-loss","-"),("Target 1","-"),("Target 2","380")]


def test_midpoint_does_not_replace_entry_range():
    source = "VKTR Buy area 760–825"
    result = api().validate_source_plan_fields(source,[field(source,"Buy area 760–825","Entry","795")])
    assert result.fields == () and result.rejected_count == 1
    assert api().validate_source_plan_fields(source,[field(source,"Buy area 760–825","Entry","760–825")]).rejected_count == 0


@pytest.mark.parametrize(("source","label","value"),[("Entry >=340","Entry",">=340"),("Stop-loss <330","Stop-loss","<330"),("SL2 <705","Stop-loss 2","<705"),("Target 1 1390–1400","Target 1","1390–1400")])
def test_explicit_comparator_and_extra_conditions_survive(source,label,value):
    raw = source + "\nValid 3 October 2026; fails if reclaim does not hold"
    result = api().validate_source_plan_fields(raw,[field(raw,source,label,value)])
    assert result.rejected_count == 0 and result.fields[0].value == value
    assert "fails if reclaim" in raw


def test_invalid_optional_field_is_omitted_without_summary_gate():
    source = "Entry 340\nTP1 360\nSupport 330"
    payload = [field(source,"Entry 340","Entry","340"),field(source,"TP1 360","Target 1","999"),field(source,"Support 330","Stop-loss","<330"),{"oops":1}]
    result = api().validate_source_plan_fields(source,payload)
    assert result.rejected_count == 3 and [f.label for f in result.fields] == ["Entry"]


def test_conflicting_duplicate_labels_are_unavailable():
    source = "Entry 340\nEntry 345"
    result = api().validate_source_plan_fields(source,[field(source,"Entry 340","Entry","340"),field(source,"Entry 345","Entry","345")])
    assert result.fields == () and result.rejected_count == 2


def test_board_reader_only_reads_canonical_labels_and_preserves_target_number():
    message = "### BULL\n**Entry:** >=340\n**Stop-loss:** <330\n**Target 2:** 380\nDate: 3 October 2026"
    fields = api().fields_from_canonical_message(message)
    assert [(f.label,f.value) for f in fields] == [("Entry",">=340"),("Stop-loss","<330"),("Target 2","380")]
    assert not api().fields_from_canonical_message("Watch on 340\nSupport utama 330")


@pytest.mark.parametrize("source", ["Entry 7600", "Entry 760–825", "Entry 760 to 825", "Entry 760 sampai 825", "Entry 760,50"])
def test_evidence_span_cannot_truncate_a_source_level(source):
    result = api().validate_source_plan_fields(source, [field(source, "Entry 760", "Entry", "760")])
    assert result.fields == ()


def test_evidence_span_cannot_turn_target_number_into_its_level():
    source = "Target 2 288"
    assert api().validate_source_plan_fields(source, [field(source, "Target 2", "Target 1", "2")]).fields == ()


@pytest.mark.parametrize(("source", "label", "value"), [
    ("Stoploss 260", "Stop-loss", "260"), ("SL 260", "Stop-loss", "260"),
    ("Target 288", "Target 1", "288"), ("TP 288", "Target 1", "288"),
    ("Target 2: 298", "Target 2", "298"), ("SL 2: <250", "Stop-loss 2", "<250"),
])
def test_label_number_is_distinct_from_source_level(source, label, value):
    result = api().validate_source_plan_fields(source, [field(source, source, label, value)])
    assert result.rejected_count == 0 and result.fields[0].value == value
