#!/usr/bin/env python3
"""
rbx-selfcheck — web UI lokal buat cek akun Roblox sendiri.
Jalan di 127.0.0.1:5000. Cookie nggak pernah keluar dari mesin ini.
"""

import json
from flask import Flask, render_template, request, jsonify
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from datetime import datetime, timezone

app = Flask(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def rbx_get(url, cookie, csrf=None):
    headers = {
        "Cookie": f".ROBLOSECURITY={cookie}",
        "User-Agent": UA,
        "Accept": "application/json",
    }
    if csrf:
        headers["X-CSRF-TOKEN"] = csrf
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} :: {body[:200]}") from None


def fetch_csrf(cookie):
    req = Request(
        "https://auth.roblox.com/v2/logout",
        headers={"Cookie": f".ROBLOSECURITY={cookie}", "User-Agent": UA},
        method="POST",
    )
    try:
        urlopen(req, timeout=10)
    except HTTPError as e:
        return e.headers.get("x-csrf-token")
    return None


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/check", methods=["POST"])
def check():
    data = request.get_json(force=True) or {}
    cookie = (data.get("cookie") or "").strip()
    if cookie.startswith(".ROBLOSECURITY="):
        cookie = cookie.split("=", 1)[1]
    if not cookie:
        return jsonify({"error": "Cookie kosong."}), 400

    try:
        me = rbx_get("https://users.roblox.com/v1/users/authenticated", cookie)
    except RuntimeError as e:
        return jsonify({"error": f"Cookie invalid atau expired: {e}"}), 401

    uid = me["id"]
    username = me["name"]
    display = me.get("displayName", username)

    rbx_get("https://auth.roblox.com/v2/logout", cookie)  # warm up_d
    csrf = safe(lambda: fetch_csrf(cookie))

    info = safe(lambda: rbx_get(f"https://users.roblox.com/v1/users/{uid}", cookie), {})
    created = info.get("created", "")
    ageays = 0
    if created:
        try:
            d = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - d).days
        except Exception:
            pass

    robux = safe(
        lambda: rbx_get(
            f"https://economy.roblox.com/v1/users/{uid}/currency", cookie
        ).get("robux", 0),
        0,
    )

    # collectibles
    items, cursor = [], ""
    while True:
        url = (f"https://inventory.roblox.com/v1/users/{uid}/assets/collectibles"
               f"?limit=100&sortOrder=Asc")
        if cursor:
            url += f"&cursor={cursor}"
        try:
            page = rbx_get(url, cookie)
        except RuntimeError:
            break
        items.extend(page.get("data", []))
        cursor = page.get("nextPageCursor")
        if not cursor:
            break

    rap = sum((i.get("recentAveragePrice") or 0) for i in items)

    twofa = safe(
        lambda: rbx_get(
            f"https://twostepverification.roblox.com/v1/users/{uid}/configuration",
            cookie,
        ),
        {},
    )
    premium = safe(
        lambda: rbx_get(
            f"https://premiumfeatures.roblox.com/v1/users/{uid}/validate-membership",
            cookie,
        ),
        False,
    )

    friends = safe(
        lambda: rbx_get(
            f"https://friends.roblox.com/v1/users/{uid}/friends/count", cookie
        ).get("count", 0),
        0,
    )
    followers = safe(
        lambda: rbx_get(
            f"https://friends.roblox.com/v1/users/{uid}/followers/count", cookie
        ).get("count", 0),
        0,
    )
    following = safe(
        lambda: rbx_get(
            f"https://friends.roblox.com/v1/users/{uid}/followings/count", cookie
        ).get("count", 0),
        0,
    )

    groups = safe(
        lambda: rbx_get(
            f"https://groups.roblox.com/v2/users/{uid}/groups/roles", cookie
        ).get("data", []),
        [],
    )

    recent = safe(
        lambda: rbx_get(
            f"https://games.roblox.com/v2/users/{uid}/recently-played"
            f"?limit=10&sortOrder=Desc", cookie
        ).get("data", []),
        [],
    )

    badges = safe(
        lambda: rbx_get(
            f"https://badges.roblox.com/v1/users/{uid}/badges"
            f"?limit=100&sortOrder=Desc", cookie
        ).get("data", []),
        [],
    )

    items.sort(key=lambda x: -(x.get("recentAveragePrice") or 0))

    return jsonify({
        "identity": {
            "username": username,
            "display": display,
            "uid": uid,
            "created": created,
            "age_days": age_days,
            "description": info.get("description", "") or "",
        },
        "economy": {"robux": robux},
        "collectibles": {
            "count": len(items),
            "rap": rap,
            "items": [
                {
                    "name": i.get("assetName", "Unknown"),
                    "price": i.get("recentAveragePrice") or 0,
                    "serial": i.get("serialNumber"),
                }
                for i in items
            ],
        },
        "security": {
            "twofa_enabled": twofa.get("enabled", False),
            "twofa_methods": [m.get("mediaType", "?") for m in (twofa.get("methods") or [])],
        },
        "premium": bool(premium),
        "social": {"friends": friends, "followers": followers, "following": following},
        "groups": [
            {
                "name": g.get("group", {}).get("name", "?"),
                "role": g.get("role", {}).get("name", "?"),
            }
            for g in groups
        ],
        "recent": [
            {"name": g.get("name", "?"), "place": g.get("placeId")} for g in recent
        ],
        "badges": [{"name": b.get("name", "?")} for b in badges],
    })


if __name__ == "__main__":
    print("→ http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
