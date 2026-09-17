from datetime import UTC, datetime, timedelta

import requests
import supersession
from models import PostKind, SourcePost
import state


def _post(post_id: str, published_at: datetime, text: str) -> dict:
    return state.serialize_post(SourcePost(
        "kutekians",
        post_id,
        f"https://x.com/Kutekians/status/{post_id}",
        published_at,
        text,
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    ))


def _record(old: dict) -> dict:
    return {
        "delivery_id": "kutekians:100",
        "profile_id": "kutekians",
        "thread_posts": [old],
        "superseded_by": None,
        "replacement_pending": False,
    }


def test_edit_history_parser_reads_x_public_edit_chain():
    document = 'edit_control:$R[1]={edit_tweet_ids:$R[2]=["100","101","102"]}'

    assert supersession.parse_edit_tweet_ids(document) == ["100", "101", "102"]


def test_candidate_requires_close_publication_time():
    published = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    old = _post("100", published, "Revenue rose 12 percent after the company raised guidance.")
    close = _post("101", published + timedelta(minutes=59), "Revenue rose 12 percent after the company raised guidance.")
    late = _post("102", published + timedelta(hours=1, minutes=1), "Revenue rose 12 percent after the company raised guidance.")

    assert supersession.is_candidate(_record(old), {"thread_posts": [close]}) is True
    assert supersession.is_candidate(_record(old), {"thread_posts": [late]}) is False


def test_candidate_matching_is_deterministic_and_uses_content_signals():
    published = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    old = _post("100", published, "Company revenue rose 12 percent after guidance was raised.")
    unrelated = _post("101", published + timedelta(minutes=20), "Good morning everyone, have a productive day.")

    assert supersession.is_candidate(_record(old), {"thread_posts": [unrelated]}) is False


class _Response:
    status_code = 200

    def __init__(self, text: str):
        self.text = text


class _Session:
    def __init__(self, response: _Response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


def test_verifier_confirms_only_explicit_x_edit_history():
    verifier = supersession.EditHistoryVerifier(_Session(_Response('edit_tweet_ids:$R[1]=["100","101"]')))

    result = verifier.verify("https://x.com/Kutekians/status/100", "100", "101")

    assert result.status == "confirmed"


def test_verifier_does_not_treat_similarity_as_replacement():
    verifier = supersession.EditHistoryVerifier(_Session(_Response('edit_tweet_ids:$R[1]=["100"]')))

    result = verifier.verify("https://x.com/Kutekians/status/100", "100", "101")

    assert result.status == "not_superseded"


def test_verifier_surfaces_unknown_source_state_without_deleting():
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("network down")

    verifier = supersession.EditHistoryVerifier(BrokenSession())

    result = verifier.verify("https://x.com/Kutekians/status/100", "100", "101")

    assert result.status == "unknown"
