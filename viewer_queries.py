"""
Data-access and external-fetch logic for the performer viewer.

No Flask in this module, and **no raw SQL** — every database read/write goes
through the ``PerformerRepository`` port (``repo``). This module owns two things:

  * the analvids.com lookups (network + HTML scraping) — an external source,
  * the /api/stats payload assembly (pulls from the port, sorts/categorizes).

Pure presentation helpers (rating sort/category) live in ``viewer_rendering.py``.
"""

import os
import re
from collections import Counter
from io import BytesIO
from urllib.parse import quote

import requests as http_requests
from PIL import Image as PIL_Image

from viewer_rendering import _RATING_HIERARCHY, _get_rating_category, _rating_sort_key


# ── Analvids.com lookups ──

def search_analvids(q: str) -> dict:
    """Search analvids.com models by name. Returns {"results": [...]} or an error dict."""
    try:
        url = f"https://www.analvids.com/models?search={quote(q)}"
        resp = http_requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {"results": [], "error": f"analvids returned {resp.status_code}"}

        html = resp.text
        results: list = []
        seen = set()

        cards = html.split('class="model-top__img"')
        for card in cards[1:]:
            url_match = re.search(
                r'href="(https://www\.analvids\.com/model/(\d+)/([^"]+))"', card[:500]
            )
            if not url_match:
                continue
            profile_url = url_match.group(1)
            model_id = int(url_match.group(2))
            slug = url_match.group(3)
            name_match = re.search(r'class="model-top__name"[^>]*>([^<]+)<', card[:800])
            if not name_match:
                continue
            name = name_match.group(1).strip()
            if name in seen:
                continue
            seen.add(name)

            scenes = None
            scene_match = re.search(r'<b>(\d+)</b>\s*scenes?', card[:1500])
            if scene_match:
                scenes = int(scene_match.group(1))

            nationality = None
            flag_match = re.search(r'/assets/img/flags/(\w+)\.png', card[:800])
            if flag_match:
                nationality = flag_match.group(1).upper()

            results.append({
                "name": name, "url": profile_url,
                "model_id": model_id, "scenes": scenes,
                "nationality": nationality,
            })

        return {"results": results[:10]}
    except Exception as e:
        return {"results": [], "error": str(e)}


def fetch_analvids_profile(raw: str, repo) -> dict:
    """
    Resolve a performer name or analvids.com URL to a profile, scraping the
    model page and caching the profile image as a local webp thumbnail via the
    repository port. Returns the profile dict or {"error": ...}.
    """
    if not raw:
        return {"error": "Paste a name or analvids.com URL"}

    try:
        if "." not in raw or raw.startswith("http"):
            profile_url = raw
            if not profile_url.startswith("http"):
                parts = raw.strip().split()
                candidates = []
                if len(parts) >= 2:
                    candidates.append('_'.join(p.lower() for p in parts))
                    candidates.append(''.join(p.lower() for p in parts))
                else:
                    candidates.append(raw.lower())

                profile_url = None
                for candidate in candidates:
                    test_url = f"https://www.analvids.com/model/0/{candidate}"
                    resp = http_requests.get(
                        test_url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                        allow_redirects=True,
                    )
                    if resp.status_code == 200 and '/model/' in resp.url and resp.url != test_url:
                        profile_url = resp.url
                        break

                if not profile_url:
                    search_url = f"https://www.analvids.com/search/{quote(raw)}"
                    resp = http_requests.get(
                        search_url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                        allow_redirects=False,
                    )
                    loc = resp.headers.get('Location', '')
                    if resp.status_code in (301, 302) and '/model/' in loc:
                        if not loc.startswith('http'):
                            loc = 'https://www.analvids.com' + loc
                        profile_url = loc

                if not profile_url:
                    resp = http_requests.get(
                        f"https://html.duckduckgo.com/html/?q=analvids.com+{quote(raw)}",
                        timeout=10, headers={"User-Agent": "Mozilla/5.0"},
                    )
                    m = re.search(r'analvids\.com/model/(\d+)/([a-z_]+)', resp.text)
                    if m:
                        profile_url = f"https://www.analvids.com/model/{m.group(1)}/{m.group(2)}"
        else:
            profile_url = raw

        resp = http_requests.get(profile_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {"error": f"analvids returned {resp.status_code}"}

        html = resp.text
        url_match = re.search(r'/model/(\d+)', profile_url)
        model_id = int(url_match.group(1)) if url_match else None

        name = None
        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if name_match:
            name = name_match.group(1).strip()
        if not name:
            name_match = re.search(r'<title>([^|<]+)', html)
            if name_match:
                name = name_match.group(1).strip()

        nationality = None
        flag_match = re.search(r'/assets/img/flags/(\w+)\.png', html)
        if flag_match:
            nationality = flag_match.group(1).upper()

        scenes = None
        scene_match = re.search(r'<b>(\d+)</b>\s*scenes?', html)
        if scene_match:
            scenes = int(scene_match.group(1))

        image = None
        img_match = re.search(r'class="model__bg"[^>]*src="([^"]+)"', html)
        if img_match:
            image = img_match.group(1).replace('&amp;', '&')
        if not image:
            img_match = re.search(r'data-src="([^"]*cdn77[^"]*w=420[^"]+)"', html)
            if img_match:
                image = img_match.group(1).replace('&amp;', '&')

        if not name:
            return {"error": "Could not extract performer name"}

        # Store profile image as webp thumbnail (filesystem + DB via the port)
        local_image = None
        if image and model_id:
            try:
                static_dir = os.path.join(os.path.dirname(__file__), "static", "images")
                os.makedirs(static_dir, exist_ok=True)

                img_resp = http_requests.get(image, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if img_resp.status_code == 200:
                    img_data = PIL_Image.open(BytesIO(img_resp.content))
                    max_w = 300
                    if img_data.width > max_w:
                        ratio = max_w / img_data.width
                        new_h = int(img_data.height * ratio)
                        img_data = img_data.resize((max_w, new_h), PIL_Image.LANCZOS)

                    fname = f"{model_id}.webp"
                    local_path = os.path.join(static_dir, fname)
                    img_data.save(local_path, "WEBP", quality=75)
                    local_image = f"/performers/static/images/{fname}"

                    repo.save_profile_image(model_id, image, local_image)
            except Exception:
                pass

        return {
            "name": name, "url": profile_url,
            "model_id": model_id, "scenes": scenes,
            "nationality": nationality, "image": image,
            "local_image": local_image,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Stats payload ──

def build_stats_payload(repo) -> dict:
    """Assemble the full /api/stats payload from the repository port."""
    stats = repo.get_stats()

    rated = repo.get_all_rated()
    sorted_rated = sorted(rated, key=lambda x: _rating_sort_key(x["rating"]), reverse=True)
    top_rated = sorted_rated[:10]
    bottom_rated = sorted_rated[-10:][::-1]

    avg_alphabetical = (
        round(sum(_rating_sort_key(p["rating"]) for p in sorted_rated) / len(sorted_rated), 2)
        if sorted_rated else 0.0
    )

    categories = [(_get_rating_category(p["rating"]), p["rating"]) for p in rated]
    rating_counts = Counter(cat for cat, _ in categories)
    dist_list = [{"range": cat, "count": cnt} for cat, cnt in rating_counts.items()]
    dist_list.sort(key=lambda x: _RATING_HIERARCHY.get(x["range"], 999))

    most_crawled = repo.get_most_crawled(10)

    return {
        "total_performers": stats["total_performers"],
        "total_items": stats["total_items"],
        "dap_performers": stats["dap_performers"],
        "total_scenes": stats["total_scenes"],
        "rating_distribution": dist_list,
        "rated_performers": len(rated),
        "avg_rating": avg_alphabetical,
        "numeric_avg_rating": stats["numeric_avg_rating"],
        "top_rated": top_rated,
        "bottom_rated": bottom_rated,
        "most_crawled": most_crawled,
    }
