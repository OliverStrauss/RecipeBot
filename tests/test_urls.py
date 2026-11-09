import pytest

from recipe_bot.pipeline.urls import VideoLink, find_links, normalize


@pytest.mark.parametrize("raw, expected", [
    ("https://www.tiktok.com/@chef.joe/video/7312345678901234567?is_from_webapp=1&sender_device=pc",
     VideoLink("tiktok", "https://www.tiktok.com/@chef.joe/video/7312345678901234567")),
    ("https://m.tiktok.com/@chef_joe/video/7312345678901234567",
     VideoLink("tiktok", "https://www.tiktok.com/@chef_joe/video/7312345678901234567")),
    ("https://vm.tiktok.com/ZMabc123/", VideoLink("tiktok", "https://vm.tiktok.com/ZMabc123/")),
    ("https://vt.tiktok.com/ZSxyz9", VideoLink("tiktok", "https://vm.tiktok.com/ZSxyz9/")),
    ("https://www.tiktok.com/t/ZTRabc/", VideoLink("tiktok", "https://www.tiktok.com/t/ZTRabc/")),
    ("https://www.instagram.com/reel/C1a2B3c-_d/?igsh=MTc4MmM1YmI2Ng==",
     VideoLink("instagram", "https://www.instagram.com/reel/C1a2B3c-_d/")),
    ("https://instagram.com/reels/C1a2B3c/", VideoLink("instagram", "https://www.instagram.com/reel/C1a2B3c/")),
    ("https://www.instagram.com/p/C1a2B3c/", VideoLink("instagram", "https://www.instagram.com/reel/C1a2B3c/")),
    ("https://www.instagram.com/some.cook/reel/C1a2B3c/", VideoLink("instagram", "https://www.instagram.com/reel/C1a2B3c/")),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://www.youtube.com/watch?v=abc",
    "https://www.tiktok.com/@chef.joe",  # profile, not a video
    "https://www.instagram.com/chef.joe/",
    "https://example.com/tiktok.com/@a/video/1",
])
def test_rejects_unsupported(raw):
    assert normalize(raw) is None


def test_find_links_in_message():
    text = (
        "try this!! <https://www.tiktok.com/@a/video/123?lang=en> and "
        "(https://www.instagram.com/reel/XYZ/) also https://www.tiktok.com/@a/video/123 again, "
        "plus https://youtu.be/nope"
    )
    assert find_links(text) == [
        VideoLink("tiktok", "https://www.tiktok.com/@a/video/123"),
        VideoLink("instagram", "https://www.instagram.com/reel/XYZ/"),
    ]


def test_find_links_none():
    assert find_links("no links here") == []
