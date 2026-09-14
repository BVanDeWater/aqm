from newsapi import NewsApiClient
import os
from pathlib import Path
import pickle as pkl
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client() -> NewsApiClient:
    """Lazily initialize the NewsAPI client so import doesn't crash without a key."""
    global _client
    if _client is None:
        key = os.getenv("NEWSAPI_KEY")
        if not key:
            raise RuntimeError(
                "NEWSAPI_KEY environment variable is not set. "
                "Add it to your .env file for local development, or set it as a "
                "Cloud Run environment variable for production."
            )
        # Strip quotes in case they were included by Docker's --env-file
        key = key.strip('"').strip("'")
        _client = NewsApiClient(key)
    return _client

q_str = ('"air quality" '
         'AND ("pollution" OR "monitor" OR "epa" OR "environmental protection agency")')

def query(q_str=q_str, us_only=True, start=None, end=None):
    """
    Query the API with the string defined above.
    """
    news_json = _get_client().get_everything(q=q_str, from_param=start, to=end)
    if us_only == True:
        us_sources = get_us_sources()
        us_articles = [art for art in news_json["articles"]
                       if art["source"]["name"] in us_sources]
        news_json["articles"] = us_articles
        news_json["totalResults"] = len(us_articles)
    return news_json


def get_us_sources(cache=True):
    """
    Retrieve the set of all US sources.
    """
    known_us_sources = {
        "Rolling Stone",
        "Salon",
        "Scientific American",
        "The Atlantic",
        "Environmental Defense Fund",
        "Huffpost",
    }

    if cache:
        cache_dir = Path("./data/cache")
        cache_file = cache_dir / "us_sources.pkl"
        if os.path.exists(cache_file):
            with open(cache_file, "rb") as pkl_fh:
                us_sources = pkl.load(pkl_fh)
            return us_sources | known_us_sources
    sources_json = _get_client().get_sources(country="us")
    us_sources = {source["name"] for source in sources_json["sources"]}
    if cache:
        cache_dir = Path("./data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "us_sources.pkl"
        with open(cache_file, "wb") as pkl_fh:
            pkl.dump(us_sources, pkl_fh)
    return us_sources | known_us_sources