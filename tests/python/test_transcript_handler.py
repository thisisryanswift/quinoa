import json

from quinoa.ui.transcript_handler import (
    _unescape_json_string,
    apply_speaker_names,
    format_action_item,
    format_transcript_display,
    parse_transcription_result,
    utterances_from_json,
    utterances_to_json,
)


def test_unescape_json_string():
    # Standard unescaping
    assert _unescape_json_string("Hello\\nWorld") == "Hello\nWorld"
    assert _unescape_json_string('He said \\"Hi\\"') == 'He said "Hi"'
    assert _unescape_json_string("Backslash: \\\\\\\\") == "Backslash: \\\\"

    # Unicode escapes
    assert _unescape_json_string("Caf\\u00e9") == "Café"

    # Manual fallback for invalid sequences (should return as is or partially handled)
    assert _unescape_json_string("Invalid \\z sequence") == "Invalid \\z sequence"

    # Ordering check (\\\\n vs \\n)
    # \\\\n in JSON source means literal backslash then n.
    # Regex capture gives \\n
    assert _unescape_json_string("\\\\n") == "\\n"


def test_parse_valid_json():
    json_str = json.dumps(
        {
            "utterances": [
                {
                    "speaker": "Me",
                    "text": "Hello world",
                    "start_time": "00:01",
                    "end_time": "00:02",
                },
                {
                    "speaker": "Speaker 2",
                    "text": "Hi there",
                    "start_time": "00:03",
                    "end_time": "00:04",
                },
            ],
            "summary": "Greeting session",
            "action_items": [{"text": "Say hello", "assignee": "Me"}],
        }
    )

    result = parse_transcription_result(json_str)

    assert len(result["utterances"]) == 2
    assert result["summary"] == "Greeting session"
    assert len(result["action_items"]) == 1
    assert "Me: Hello world" in result["transcript"]
    assert "[00:01] Me: Hello world" in result["transcript"]
    assert not result["parse_error"]


def test_parse_markdown_fences():
    json_data = {"utterances": [{"speaker": "Me", "text": "Inside fence"}]}
    json_str = f"```json\n{json.dumps(json_data)}\n```"

    result = parse_transcription_result(json_str)
    assert len(result["utterances"]) == 1
    assert result["utterances"][0]["text"] == "Inside fence"


def test_parse_truncated_json_recovery():
    # Truncated mid-utterance
    json_str = """
    {
      "utterances": [
        {
          "speaker": "Me",
          "text": "First message",
          "start_time": "00:01"
        },
        {
          "speaker": "Speaker 2",
          "text": "Second message",
          "start_time": "00:05"
    """

    result = parse_transcription_result(json_str)

    # Should recover at least the first complete utterance
    assert len(result["utterances"]) >= 1
    assert result["utterances"][0]["speaker"] == "Me"
    assert result["utterances"][0]["text"] == "First message"
    assert result["utterances"][0]["start_time"] == "00:01"
    assert not result["parse_error"]


def test_parse_escaped_characters_recovery():
    # Truncated JSON to force regex path
    json_str = """
    {
      "utterances": [
        {
          "speaker": "O'Brien",
          "text": "He said \\"Hello\\", then left.\\nNext line.",
          "start_time": "00:10"
        }
    """

    result = parse_transcription_result(json_str)

    assert len(result["utterances"]) == 1
    assert result["utterances"][0]["speaker"] == "O'Brien"
    assert 'He said "Hello"' in result["utterances"][0]["text"]
    assert "\nNext line." in result["utterances"][0]["text"]


def test_parse_top_level_list():
    # Valid JSON top-level list
    json_str = """
    [
      {
        "text": "Reordered fields",
        "start_time": "01:23",
        "speaker": "Flexible"
      }
    ]
    """

    result = parse_transcription_result(json_str)

    assert len(result["utterances"]) == 1
    assert result["utterances"][0]["speaker"] == "Flexible"
    assert result["utterances"][0]["text"] == "Reordered fields"
    assert result["utterances"][0]["start_time"] == "01:23"


def test_parse_top_level_list_invalid_shape():
    # Bare strings should be rejected by shape check
    json_str = '["hello", "world"]'
    result = parse_transcription_result(json_str)
    assert result["utterances"] == []
    assert result["transcript"] == ""


def test_parse_extra_fields_ignored():
    # Valid JSON with extra fields
    json_str = """
    {
      "utterances": [
        {
          "speaker": "Me",
          "text": "Message with noise",
          "confidence": 0.98,
          "random_field": "ignore me"
        }
      ]
    }
    """

    result = parse_transcription_result(json_str)

    assert len(result["utterances"]) == 1
    assert result["utterances"][0]["speaker"] == "Me"
    assert result["utterances"][0]["text"] == "Message with noise"


def test_parse_braces_limitation_recovery():
    # Documenting the known limitation: literal braces in text cause skip in regex recovery
    json_str = """
    {
      "utterances": [
        {
          "speaker": "Me",
          "text": "Valid message"
        },
        {
          "speaker": "Coder",
          "text": "Message with { braces }"
        }
    """  # Note: No closing ] or } to force regex path

    result = parse_transcription_result(json_str)

    # Should find "Valid message" but skip "Message with { braces }"
    texts = [u["text"] for u in result["utterances"]]
    assert "Valid message" in texts
    assert "Message with { braces }" not in texts


def test_parse_empty_garbage():
    result = parse_transcription_result("Not even close to JSON")
    assert result["parse_error"]
    assert result["utterances"] == []


def test_parse_top_level_list_mixed_garbage():
    # Only dictionary items with 'speaker' should be kept
    json_str = json.dumps(
        [
            {"speaker": "A", "text": "valid"},
            "garbage string",
            {"not_a_speaker": "invalid"},
            {"speaker": "B", "text": "also valid"},
        ]
    )
    result = parse_transcription_result(json_str)
    assert len(result["utterances"]) == 2
    assert result["utterances"][0]["speaker"] == "A"
    assert result["utterances"][1]["speaker"] == "B"


def test_helpers():
    # format_transcript_display
    assert format_transcript_display("text", "sum") == "## Summary\nsum\n\n## Transcript\ntext"
    assert format_transcript_display("text", "") == "text"

    # utterances_to_json / from_json
    utts = [{"speaker": "Me", "text": "hi"}]
    js = utterances_to_json(utts)
    assert "Me" in js
    assert utterances_from_json(js) == utts
    assert utterances_from_json(None) == []
    assert utterances_from_json("invalid") == []

    # apply_speaker_names
    utts = [{"speaker": "Speaker 1", "text": "hi"}]
    names = {"Speaker 1": "Alice"}
    applied = apply_speaker_names(utts, names)
    assert applied[0]["display_speaker"] == "Alice"

    # format_action_item
    assert format_action_item({"text": "Task", "assignee": "Me"}) == "Task (Me)"
    assert format_action_item({"text": "Task", "assignee": None}) == "Task"
