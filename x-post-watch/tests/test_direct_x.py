import direct_x
from models import PostKind


class Response:
    def __init__(self, status_code, *, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


class Session:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout, headers=None):
        assert timeout == 30
        self.urls.append(url)
        if url == "https://x.com/Kutekians":
            return Response(200, text='<article data-tweet-id="101"></article>')
        if url == "https://x.com/Kutekians/status/101":
            return Response(200, text='<article data-tweet-id="101"></article><article data-tweet-id="102"></article>')
        if url == "https://api.vxtwitter.com/Kutekians/status/101":
            return Response(200, payload={
                "tweetID": "101",
                "tweetURL": "https://twitter.com/Kutekians/status/101",
                "date_epoch": 1787137418,
                "text": "Root context",
                "mediaURLs": ["https://pbs.twimg.com/media/root.jpg"],
                "replyingTo": None,
                "replyingToID": None,
                "user_screen_name": "Kutekians",
            })
        if url == "https://api.vxtwitter.com/Kutekians/status/102":
            return Response(200, payload={
                "tweetID": "102",
                "tweetURL": "https://twitter.com/Kutekians/status/102",
                "date_epoch": 1787137419,
                "text": "Continuation",
                "mediaURLs": [],
                "replyingTo": "Kutekians",
                "replyingToID": "101",
                "user_screen_name": "Kutekians",
            })
        raise AssertionError(f"unexpected URL: {url}")


class ModernProfileSession(Session):
    def get(self, url, timeout, headers=None):
        if url == "https://x.com/Kutekians":
            return Response(
                200,
                text=(
                    '<a href="/i/status/999">quoted post</a>'
                    '<a href="/Kutekians/status/101">own post</a>'
                    '<a href="/other/status/202">other post</a>'
                ),
            )
        return super().get(url, timeout, headers=headers)


def test_fetches_and_expands_a_same_author_thread(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    posts = direct_x.fetch_profile_items(profile, Session(), after_id=100)

    assert [post.post_id for post in posts] == ["101", "102"]
    assert [post.kind for post in posts] == [PostKind.NORMAL, PostKind.REPLY]
    assert posts[1].related_url == "https://x.com/Kutekians/status/101"
    assert posts[0].content_html == "Root context"
    assert [media.url for media in posts[0].media] == ["https://pbs.twimg.com/media/root.jpg"]


def test_discovers_posts_from_current_profile_status_links(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    posts = direct_x.fetch_profile_items(profile, ModernProfileSession(), after_id=100)

    assert [post.post_id for post in posts] == ["101", "102"]


def test_keeps_visible_profile_posts_when_no_new_thread_exists(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    session = Session()

    posts = direct_x.fetch_profile_items(profile, session, after_id=101)

    assert [post.post_id for post in posts] == ["101"]
    assert session.urls == [
        "https://x.com/Kutekians",
        "https://api.vxtwitter.com/Kutekians/status/101",
    ]
