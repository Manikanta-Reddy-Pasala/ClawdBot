import json
import os
import asyncio
from config import config

PROFILE_PATH = "/opt/clawdbot/job_profile.json"


async def search_jobs(query: str, location: str = "", site: str = "linkedin") -> str:
    """Search for jobs using web scraping."""
    try:
        from duckduckgo_search import DDGS

        # Build search query
        site_filter = ""
        if site == "linkedin":
            site_filter = "site:linkedin.com/jobs"
        elif site == "indeed":
            site_filter = "site:indeed.com/viewjob"
        elif site == "both":
            site_filter = "(site:linkedin.com/jobs OR site:indeed.com/viewjob)"

        search_query = f"{query} {location} {site_filter}".strip()

        results = await asyncio.to_thread(
            lambda: list(DDGS().text(search_query, max_results=15))
        )

        if not results:
            return "No job listings found."

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")[:80]
            url = r.get("href", "")
            snippet = r.get("body", "")[:100]
            lines.append(f"{i}. {title}\n   {snippet}\n   {url}\n")

        return f"Found {len(results)} jobs for '{query}' in '{location}':\n\n" + "\n".join(lines)

    except ImportError:
        return "duckduckgo-search package not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        return f"Job search error: {e}"


def save_profile(data: dict) -> str:
    """Save/update job seeker profile."""
    try:
        existing = {}
        if os.path.isfile(PROFILE_PATH):
            with open(PROFILE_PATH, "r") as f:
                existing = json.load(f)

        existing.update(data)

        with open(PROFILE_PATH, "w") as f:
            json.dump(existing, f, indent=2)

        return f"Profile saved with keys: {', '.join(existing.keys())}"
    except Exception as e:
        return f"Error saving profile: {e}"


def get_profile() -> str:
    """Get the saved job seeker profile."""
    try:
        if not os.path.isfile(PROFILE_PATH):
            return "No profile saved yet. Tell me about yourself and I'll save your profile."

        with open(PROFILE_PATH, "r") as f:
            profile = json.load(f)

        lines = []
        for k, v in profile.items():
            if isinstance(v, list):
                lines.append(f"{k}: {', '.join(str(i) for i in v)}")
            else:
                lines.append(f"{k}: {v}")
        return "Job Profile:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error reading profile: {e}"


async def fetch_job_details(url: str) -> str:
    """Fetch details from a specific job listing URL."""
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            # Basic HTML to text - strip tags
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            # Truncate
            return text[:6000]
    except Exception as e:
        return f"Error fetching job details: {e}"
