"""
The Air Monitor — Flask web application.

Serves a live newspaper-style page of air quality news headlines fetched from
NewsAPI. Responses are cached in-memory for CACHE_TTL seconds to stay within
NewsAPI's free-tier request limits (100 requests/day).
"""

import os
import time
import traceback
from flask import Flask, make_response, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory response cache
# ---------------------------------------------------------------------------
# Cloud Run scales to zero, so each cold start gets a fresh cache. Within a
# running instance, responses are reused for CACHE_TTL seconds to avoid
# hammering NewsAPI's 100-req/day free-tier limit.
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", 3600))  # default: 1 hour

_cache: dict = {
    "html": None,
    "us_sources": None,
    "timestamp": 0.0,
}


def _get_headlines_html() -> str:
    """Fetch or return cached newspaper HTML."""
    now = time.time()
    if _cache["html"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["html"]

    # Import here (not at module level) so startup doesn't fail without the key
    from fetchers.newsapi import query, get_us_sources
    from viz.headlines import build_page

    # Fetch US sources once and cache them alongside articles
    if _cache["us_sources"] is None:
        _cache["us_sources"] = get_us_sources(cache=False)

    articles_json = query(us_only=False)
    html = build_page(articles_json, _cache["us_sources"])

    _cache["html"] = html
    _cache["timestamp"] = now
    return html


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """Render the live Air Monitor newspaper page."""
    try:
        html = _get_headlines_html()
        resp = make_response(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp
    except RuntimeError as exc:
        # Missing API key — surface a clear message instead of a raw 500
        return make_response(
            f"<h1>Configuration Error</h1><pre>{exc}</pre>", 503
        )
    except Exception:
        return make_response(
            "<h1>Something went wrong</h1>"
            "<p>Could not fetch headlines. Please try again later.</p>"
            f"<pre>{traceback.format_exc()}</pre>",
            503,
        )


@app.route("/healthz")
def health_check():
    """Health check endpoint for Cloud Run."""
    return jsonify(status="ok"), 200


# ---------------------------------------------------------------------------
# Entry point (local development only — production uses Gunicorn)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
