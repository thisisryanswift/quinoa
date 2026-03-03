import json
from quinoa.calendar.utils import parse_attendee_names


def test_parse_attendee_names_valid():
    attendees = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob"},
        {"email": "charlie@example.com"},
    ]
    js = json.dumps(attendees)
    names = parse_attendee_names(js)
    assert names == ["Alice", "Bob", "charlie@example.com"]


def test_parse_attendee_names_bare_strings():
    attendees = ["alice@example.com", "Bob"]
    js = json.dumps(attendees)
    names = parse_attendee_names(js)
    assert names == ["alice@example.com", "Bob"]


def test_parse_attendee_names_mixed():
    attendees = [
        {"name": "Alice"},
        "bob@example.com",
        {"invalid": "data"},
        123,  # Should be ignored
    ]
    js = json.dumps(attendees)
    names = parse_attendee_names(js)
    assert names == ["Alice", "bob@example.com", "Unknown"]


def test_parse_attendee_names_none_empty():
    assert parse_attendee_names(None) == []
    assert parse_attendee_names("") == []
    assert parse_attendee_names("[]") == []


def test_parse_attendee_names_invalid_json():
    assert parse_attendee_names("not json") == []
    assert parse_attendee_names('{"not": "a list"}') == []
