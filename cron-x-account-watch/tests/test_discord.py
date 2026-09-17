import pytest
import requests

import discord


def test_post_media_marks_confirmed_missing_source_as_terminal(monkeypatch, tmp_path):
    class Missing:
        status_code = 404
        headers = {}
        content = b""

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(discord.requests, "get", lambda *args, **kwargs: Missing())

    with pytest.raises(discord.MediaUnavailable) as error:
        discord.post_media(
            "https://pbs.twimg.com/media/missing.jpg",
            "channel",
            False,
            "nonce",
            tmp_path,
        )

    assert error.value.status_code == 404
