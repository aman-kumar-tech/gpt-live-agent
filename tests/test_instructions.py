"""Pure string-builder tests for instructions.py -- no DB needed."""

from receptionist.instructions import build_reasoning_instructions, build_voice_instructions

LAB_TEXT = "Test Lab, 123 Test St. Phone +910000000000. Hours: Mon closed."


def test_voice_instructions_include_lab_facts_when_given():
    result = build_voice_instructions(lab_info_text=LAB_TEXT)
    assert "Lab facts:" in result
    assert LAB_TEXT in result


def test_voice_instructions_omit_lab_facts_when_absent():
    result = build_voice_instructions()
    assert "Lab facts:" not in result


def test_reasoning_instructions_include_lab_facts_when_given():
    result = build_reasoning_instructions(lab_info_text=LAB_TEXT)
    assert "Lab facts (already known" in result
    assert LAB_TEXT in result
    # No longer needs delegation for lab-logistics questions once given upfront.
    assert "parking, facility accessibility" not in result


def test_reasoning_instructions_still_delegate_lab_facts_when_absent():
    result = build_reasoning_instructions()
    assert "Lab facts (already known" not in result
    assert "parking, facility accessibility" in result


def test_reasoning_instructions_follow_up_after_informational_answers():
    result = build_reasoning_instructions()
    assert "once you've finished answering any informational question" in result


def test_reasoning_instructions_mention_test_list_paging():
    result = build_reasoning_instructions()
    assert "manageable page" in result
    assert "isn't reliable for confirming whether one specific named test exists" in result
