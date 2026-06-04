"""Web search backend — STUB / pluggable.

Router signature:  web_search(query)

No search API or key was specified. The shape below is ready for a provider;
fill in `_search`. Note: your LLM already streams answers (nonthinking). Decide
whether web_search should (a) return raw results for the widget, or (b) feed
results back into the LLM to summarise for TTS. Right now it returns a stub
string. Options to wire:

    • Brave Search API   (requires key)
    • SerpAPI            (requires key)
    • DuckDuckGo (ddgs)  pip install ddgs   — no key, rate-limited
"""
from typing import Optional


def _search(query: str) -> list[dict]:
    # TODO: real provider. Returns list of {title, snippet, url}.
    return [{"title": "Search not configured",
             "snippet": f"No search provider wired for: {query}",
             "url": ""}]


def web_search(query: str) -> str:
    """Spoken summary for TTS. Swap to feed the LLM if you want synthesis."""
    results = _search(query)
    if not results:
        return f"I found nothing for {query}."
    return results[0]["snippet"]
