from datetime import datetime, timezone

from conftest import FIXED_NOW
from newsdash.fetchers.rss import FULL_TEXT_MAX_CHARS, parse_feed_bytes

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>AI model released</title><link>https://ex.com/a</link>
<pubDate>Mon, 06 Jul 2026 08:00:00 GMT</pubDate>
<description><![CDATA[<p>Big <b>news</b> summary</p>]]></description></item>
<item><title>Gardening tips</title><link>https://ex.com/b</link>
<pubDate>Mon, 06 Jul 2026 09:00:00 GMT</pubDate></item>
<item><title>Undated entry</title><link>https://ex.com/c</link></item>
</channel></rss>"""


def test_parse_basic(make_source):
    items = parse_feed_bytes(RSS, make_source(), FIXED_NOW)
    assert [i.title for i in items] == ["AI model released", "Gardening tips"]
    first = items[0]
    assert first.published_at == datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)
    assert first.summary == "Big news summary"
    assert first.full_text == ""
    assert first.kind == "news"
    assert first.weight == 0.9


def test_keyword_filter(make_source):
    items = parse_feed_bytes(RSS, make_source(keywords=["AI"]), FIXED_NOW)
    assert [i.title for i in items] == ["AI model released"]


def test_embedded_content_marks_full_text(make_source):
    body = " ".join(f"paragraph-{i}" for i in range(120))
    raw = f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item><title>Long read</title><link>https://ex.com/long</link>
<pubDate>Mon, 06 Jul 2026 08:00:00 GMT</pubDate>
<description>Short summary</description>
<content:encoded><![CDATA[<article><h1>Headline</h1><p>{body}</p></article>]]></content:encoded>
</item></channel></rss>""".encode()
    item = parse_feed_bytes(raw, make_source(), FIXED_NOW)[0]
    assert item.full_text.startswith("Headline paragraph-0")
    assert "<article>" not in item.full_text
    assert len(item.full_text) > 500


def test_summary_only_does_not_mark_full_text(make_source):
    body = " ".join("summary" for _ in range(120))
    raw = f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Summary only</title><link>https://ex.com/s</link>
<pubDate>Mon, 06 Jul 2026 08:00:00 GMT</pubDate>
<description>{body}</description></item>
</channel></rss>""".encode()
    item = parse_feed_bytes(raw, make_source(), FIXED_NOW)[0]
    assert item.summary
    assert item.full_text == ""


def test_embedded_content_must_be_substantial(make_source):
    raw = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Short content</title><link>https://ex.com/short</link>
<pubDate>Mon, 06 Jul 2026 08:00:00 GMT</pubDate>
<description>Short summary</description>
<content><p>Too short to be an article.</p></content>
</item></channel></rss>"""
    item = parse_feed_bytes(raw, make_source(), FIXED_NOW)[0]
    assert item.full_text == ""


def test_embedded_content_is_capped(make_source):
    raw = f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item><title>Huge content</title><link>https://ex.com/huge</link>
<pubDate>Mon, 06 Jul 2026 08:00:00 GMT</pubDate>
<description>Short summary</description>
<content:encoded><![CDATA[<p>{"x" * (FULL_TEXT_MAX_CHARS + 1000)}</p>]]></content:encoded>
</item></channel></rss>""".encode()
    item = parse_feed_bytes(raw, make_source(), FIXED_NOW)[0]
    assert len(item.full_text) == FULL_TEXT_MAX_CHARS
