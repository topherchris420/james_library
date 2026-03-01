import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import external_integrations


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: D401, ARG002
        return False


def test_search_arxiv_does_not_double_encode_query(monkeypatch):
    seen_urls: list[str] = []
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678</id>
    <title>Sample Result</title>
    <summary>Summary</summary>
    <author><name>Author One</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/1234.5678.pdf" />
  </entry>
</feed>
"""

    def _fake_urlopen(url, timeout):  # noqa: ARG001
        seen_urls.append(url)
        return _FakeResponse(xml)

    monkeypatch.setattr(external_integrations.urllib.request, "urlopen", _fake_urlopen)
    result = external_integrations.search_arxiv("quantum resonance", max_results=1)

    assert "Sample Result" in result
    assert seen_urls
    assert "%2520" not in seen_urls[0]
