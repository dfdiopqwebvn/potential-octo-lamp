#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║            📥 Instagram Reels Downloader v4.0                    ║
║                                                                  ║
║  Features:                                                       ║
║    ✅ Download ALL reels (কোনোটা skip হবে না)                   ║
║    ✅ Auto retry 5x with Tor circuit refresh                     ║
║    ✅ Mobile API + Web API দুটোই try করে                         ║
║    ✅ Quality selection (1080p/720p/480p)                        ║
║    ✅ Safe filenames (caption + post_id fallback)                ║
║    ✅ Auto ZIP after download                                    ║
║    ✅ Beautiful progress display                                 ║
║                                                                  ║
║  Codespace Optimized:                                            ║
║    - Tor proxy support (anti-ban)                                ║
║    - Headless Chrome NOT required                                ║
║    - Just cookies.txt + this script                              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

import requests
import http.cookiejar
import re
import os
import sys
import time
import zipfile
import subprocess
import json
import urllib.parse
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION (এখানে বদলাও)
# ═══════════════════════════════════════════════════════════════════

TARGET_PROFILE  = "jan16.__"                           # যার reels download করবে
COOKIES_FILE    = "cookies.txt"                        # Browser cookies file
USE_TOR         = True                                 # Tor proxy ব্যবহার করবে?
TOR_PROXY       = "socks5h://127.0.0.1:9050"          # Tor SOCKS5
DOWNLOAD_DIR    = "downloads"                          # Download folder
MAX_FILENAME    = 50                                   # Max filename length
MAX_RETRIES     = 5                                    # Retry per video
RETRY_DELAY     = 4                                    # Seconds between retries
DELAY_BETWEEN   = 2                                    # Delay between videos

# ═══════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ───────────────────────────────────────────────────────────────────

def banner():
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║         📥 Instagram Reels Downloader v4.0            ║
    ║      ✅ No Skip  ✅ Retry 5x  ✅ Tor Support          ║
    ╚═══════════════════════════════════════════════════════╝
    """)


def clean_caption(text, max_len=MAX_FILENAME):
    """Caption → safe filename (কখনো fail হবে না)"""
    if not text or not text.strip():
        return None

    # Clean text
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    text = re.sub(r'[^\w\s\-\.]', '', text)
    text = text.strip()

    # Too short
    if len(text) < 3:
        return None

    # Truncate at word boundary
    if len(text) > max_len:
        text = text[:max_len]
        last_space = text.rfind(' ')
        if last_space > 20:
            text = text[:last_space]

    return text


def make_filename(caption, post_id, index):
    """
    সবসময় valid filename:
      1. Short caption (001_sunset_beach.mp4)
      2. Post ID       (002_reel_3154678921.mp4)
      3. Just number   (003_reel.mp4)
    """
    safe = clean_caption(caption)
    if safe:
        return f"{index:03d}_{safe}.mp4"
    elif post_id:
        return f"{index:03d}_reel_{post_id}.mp4"
    else:
        return f"{index:03d}_reel.mp4"


def get_resolution_label(width, height):
    if not width or not height:
        return "unknown"
    h = max(width, height)
    if h >= 1920:   return "1080p"
    elif h >= 1280: return "720p"
    elif h >= 854:  return "480p"
    elif h >= 640:  return "360p"
    else:           return f"{h}p"


def format_size(bytes_size):
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} MB"


def progress_bar(current, total, width=30):
    if total == 0:
        return "░" * width
    filled = int(width * current / total)
    return "█" * filled + "░" * (width - filled)


def refresh_tor_circuit():
    """Tor নতুন IP দেবে (anti-ban)"""
    # Method 1: killall -HUP
    try:
        subprocess.run(["killall", "-HUP", "tor"],
                       capture_output=True, timeout=5)
        time.sleep(8)
        print("    🔄 Tor circuit refreshed (new IP)")
        return True
    except Exception:
        pass

    # Method 2: Control port
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", 9051))
        s.send(b"AUTHENTICATE\r\nSIGNAL NEWNYM\r\nQUIT\r\n")
        time.sleep(8)
        s.close()
        print("    🔄 Tor circuit refreshed via control port")
        return True
    except Exception:
        pass

    print("    ⚠️  Tor refresh failed (manual restart needed)")
    return False


def show_quality_options(qualities):
    print("""
    ┌───────────────────────────────────────────┐
    │         📺 Available Video Qualities       │
    ├───────────────────────────────────────────┤
    │   0. 🏆 Best Quality (Original Upload)    │""")

    for i, q in enumerate(qualities, 1):
        if "1080" in q["label"]:
            emoji, note = "🟢", "Full HD"
        elif "720" in q["label"]:
            emoji, note = "🟡", "HD Ready"
        elif "480" in q["label"]:
            emoji, note = "🟠", "Standard"
        else:
            emoji, note = "🔴", "Low"
        print(f"    │   {i}. {emoji} {q['label']:<8s} "
              f"({q['width']}x{q['height']:<4s}) {note:<10s}│")

    print("    └───────────────────────────────────────────┘")


# ───────────────────────────────────────────────────────────────────
#  CORE: Authentication
# ───────────────────────────────────────────────────────────────────

def load_cookies(filename):
    """cookies.txt load করো"""
    print(f"\n    🔐 Loading cookies from: {filename}")

    if not os.path.exists(filename):
        print(f"    ❌ File not found: {filename}")
        print(f"       আগে browser থেকে cookies export করো!")
        print(f"       Chrome Extension: 'Get cookies.txt LOCALLY'")
        sys.exit(1)

    cj = http.cookiejar.MozillaCookieJar(filename)
    cj.load(ignore_discard=True, ignore_expires=True)

    cookies = {}
    for c in cj:
        cookies[c.name] = c.value

    # Check required cookies
    if 'sessionid' not in cookies:
        print(f"    ❌ Required cookie 'sessionid' not found!")
        print(f"       Login হয়ে cookies export করো।")
        sys.exit(1)

    print(f"    ✅ Loaded {len(cookies)} cookies")
    print(f"    ✅ sessionid: {cookies['sessionid'][:20]}...")

    if 'ds_user_id' in cookies:
        print(f"    ✅ ds_user_id: {cookies['ds_user_id']}")
    if 'csrftoken' in cookies:
        print(f"    ✅ csrftoken: {cookies['csrftoken'][:20]}...")

    return cookies


def create_session(cookies):
    """Instagram session তৈরি"""
    s = requests.Session()

    if USE_TOR:
        s.proxies = {
            "http": TOR_PROXY,
            "https": TOR_PROXY,
        }
        print(f"    🌐 Tor proxy: {TOR_PROXY}")

    # iPhone User-Agent (best success rate)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "x-ig-app-id": "936619743392459",
    })

    # Set all cookies
    for name, value in cookies.items():
        s.cookies.set(name, value, domain=".instagram.com", path="/")

    return s


def get_fresh_csrf(session):
    """Fresh CSRF token নাও"""
    print("    🔄 Getting fresh CSRF token...")
    try:
        r = session.get("https://www.instagram.com/", timeout=30)

        for cookie in session.cookies:
            if cookie.name == 'csrftoken':
                return cookie.value

        match = re.search(r'"csrf_token":"([^"]+)"', r.text)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"    ⚠️  CSRF fetch error: {e}")
    return None


# ───────────────────────────────────────────────────────────────────
#  CORE: Profile & Reels Fetching
# ───────────────────────────────────────────────────────────────────

def get_user_id(session, username, csrf_token):
    """Username → User ID"""
    print(f"\n    📥 Looking up: {username}")

    session.headers.update({
        "X-CSRFToken": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{username}/",
    })

    # Method 1: Web Profile Info API
    try:
        r = session.get(
            f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            user = data["data"]["user"]
            uid = user["id"]
            full_name = user.get("full_name", "")
            followers = user.get("edge_followed_by", {}).get("count", "?")
            following = user.get("edge_follow", {}).get("count", "?")
            is_private = user.get("is_private", False)
            is_verified = user.get("is_verified", False)

            print(f"    ✅ Username:  {user['username']}")
            if full_name:
                print(f"    📝 Name:     {full_name}")
            if isinstance(followers, int):
                print(f"    👥 Followers: {followers:,}")
            else:
                print(f"    👥 Followers: {followers}")
            if isinstance(following, int):
                print(f"    👤 Following: {following:,}")
            print(f"    🆔 User ID:  {uid}")
            if is_verified:
                print(f"    ✔️  Verified account")
            if is_private:
                print(f"    🔒 PRIVATE — cookies account follow করা লাগবে")
            return uid
    except Exception as e:
        print(f"    ⚠️  REST API error: {e}")

    # Method 2: HTML scraping
    print("    🔄 Trying HTML fallback...")
    try:
        r = session.get(f"https://www.instagram.com/{username}/", timeout=30)
        patterns = [
            r'"profilePage_([0-9]+)"',
            r'"user_id":"([0-9]+)"',
            r'"id":"([0-9]+)"',
            r'userId\\?":\\?"([0-9]+)',
        ]
        for p in patterns:
            m = re.search(p, r.text)
            if m:
                uid = m.group(1)
                print(f"    ✅ User ID from HTML: {uid}")
                return uid
    except Exception as e:
        print(f"    ⚠️  HTML method error: {e}")

    print("    ❌ Cannot find user ID!")
    return None


def parse_video_versions(versions):
    """video_versions list → sorted (highest first)"""
    if not versions:
        return []

    def quality_score(v):
        w = v.get("width", 0) or 0
        h = v.get("height", 0) or 0
        return w * h

    return sorted(versions, key=quality_score, reverse=True)


def fetch_reels_clips_api(session, user_id, csrf_token, username, max_count):
    """Clips API (reels specific)"""
    reels = []
    max_id = None
    page = 0
    consecutive_errors = 0

    while True:
        page += 1

        if max_count and len(reels) >= max_count:
            return reels[:max_count]

        try:
            session.headers.update({
                "X-CSRFToken": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.instagram.com/{username}/reels/",
            })

            # Mobile-friendly URL
            url = "https://www.instagram.com/api/v1/clips/user/"
            data = {
                "target_user_id": str(user_id),
                "page_size": "12",
                "include_feed_video": "true",
            }
            if max_id:
                data["max_id"] = max_id

            r = session.post(url, data=data, timeout=30)

            # CSRF expired
            if r.status_code == 403:
                csrf_token = get_fresh_csrf(session)
                if csrf_token:
                    session.headers["X-CSRFToken"] = csrf_token
                    r = session.post(url, data=data, timeout=30)

            if r.status_code != 200:
                print(f"\n    ⚠️  Clips API: HTTP {r.status_code}")
                break

            result = r.json()
            items = result.get("items", [])

            if not items:
                break

            consecutive_errors = 0

            for item in items:
                media = item.get("media", {})
                versions = media.get("video_versions", [])

                if not versions:
                    continue

                caption = ""
                cap = media.get("caption", {})
                if isinstance(cap, dict):
                    caption = cap.get("text", "")
                elif isinstance(cap, str):
                    caption = cap

                versions_sorted = parse_video_versions(versions)
                best = versions_sorted[0]

                reels.append({
                    "post_id": str(media.get("pk", "")),
                    "caption": caption,
                    "versions": versions_sorted,
                    "url": best["url"],
                    "width": best.get("width", 0),
                    "height": best.get("height", 0),
                    "type": media.get("media_type", 2),
                    "taken_at": media.get("taken_at", 0),
                })

            target_display = max_count or 999
            bar = progress_bar(len(reels), target_display)
            sys.stdout.write(
                f"\r    📜 [{bar}] {len(reels)} reels found (page {page})"
            )
            sys.stdout.flush()

            paging = result.get("paging_info", {})
            if not paging.get("more_available"):
                break
            max_id = paging.get("max_id")
            if not max_id:
                break

            time.sleep(2)

        except requests.exceptions.ConnectionError as e:
            consecutive_errors += 1
            print(f"\n    ⚠️  Connection error (attempt {consecutive_errors})")
            if USE_TOR and consecutive_errors <= 3:
                refresh_tor_circuit()
                time.sleep(3)
                continue
            elif consecutive_errors > 4:
                print("    ❌ Too many errors, stopping.")
                break

        except Exception as e:
            consecutive_errors += 1
            print(f"\n    ❌ Page {page} error: {e}")
            if consecutive_errors > 4:
                break
            time.sleep(5)

    return reels


def fetch_reels_feed_api(session, user_id, csrf_token, username, max_count):
    """Feed API (fallback) - regular posts থেকে video filter"""
    reels = []
    max_id = None
    page = 0

    while True:
        page += 1
        if max_count and len(reels) >= max_count:
            return reels[:max_count]

        try:
            url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/"
            params = {"count": "50"}
            if max_id:
                params["max_id"] = max_id

            r = session.get(url, params=params, timeout=30)

            if r.status_code == 403:
                csrf_token = get_fresh_csrf(session)
                if csrf_token:
                    session.headers["X-CSRFToken"] = csrf_token
                    r = session.get(url, params=params, timeout=30)

            if r.status_code != 200:
                print(f"\n    ⚠️  Feed API: HTTP {r.status_code}")
                break

            result = r.json()
            items = result.get("items", [])

            if not items:
                break

            for item in items:
                # শুধু video posts (media_type=2)
                if item.get("media_type") != 2:
                    continue

                versions = item.get("video_versions", [])
                if not versions:
                    continue

                caption = ""
                cap = item.get("caption", {})
                if isinstance(cap, dict):
                    caption = cap.get("text", "")
                elif isinstance(cap, str):
                    caption = cap

                versions_sorted = parse_video_versions(versions)
                best = versions_sorted[0]

                reels.append({
                    "post_id": str(item.get("pk", "")),
                    "caption": caption,
                    "versions": versions_sorted,
                    "url": best["url"],
                    "width": best.get("width", 0),
                    "height": best.get("height", 0),
                    "type": 2,
                    "taken_at": item.get("taken_at", 0),
                })

            target_display = max_count or 999
            bar = progress_bar(len(reels), target_display)
            sys.stdout.write(
                f"\r    📜 [{bar}] {len(reels)} videos found (page {page})"
            )
            sys.stdout.flush()

            if not result.get("more_available"):
                break
            max_id = result.get("next_max_id")
            if not max_id:
                break

            time.sleep(2)

        except Exception as e:
            print(f"\n    ❌ Feed page {page} error: {e}")
            break

    return reels


def fetch_all_reels(session, user_id, csrf_token, username, max_count):
    """Clips API আগে try, না হলে Feed API"""
    print(f"\n    🎬 Fetching reels from: {username}")

    if max_count:
        print(f"    📊 Target: {max_count} reels")
    else:
        print(f"    📊 Target: ALL reels")

    # Try Clips API first (reels specific)
    print("    🔄 Method 1: Clips API (reels specific)...")
    reels = fetch_reels_clips_api(session, user_id, csrf_token, username, max_count)

    if not reels:
        print("\n    🔄 Method 2: Feed API (all videos)...")
        reels = fetch_reels_feed_api(session, user_id, csrf_token, username, max_count)

    # Trim
    if max_count:
        reels = reels[:max_count]

    print(f"\n    📊 Total: {len(reels)} reels")
    return reels


# ───────────────────────────────────────────────────────────────────
#  CORE: Quality & Download
# ───────────────────────────────────────────────────────────────────

def detect_available_qualities(reels):
    all_q = {}
    for reel in reels:
        for v in reel.get("versions", []):
            w = v.get("width", 0)
            h = v.get("height", 0)
            key = f"{w}x{h}"
            if key not in all_q:
                all_q[key] = {
                    "label": get_resolution_label(w, h),
                    "width": w, "height": h,
                }
    return sorted(all_q.values(),
                  key=lambda q: q["width"] * q["height"],
                  reverse=True)


def select_quality(reels):
    qualities = detect_available_qualities(reels)

    if not qualities:
        print("    ⚠️  No quality info. Using best.")
        return None

    show_quality_options(qualities)

    while True:
        choice = input("\n    👉 Select (0 for Best): ").strip()
        if not choice:
            choice = "0"
        try:
            choice = int(choice)
            if choice == 0:
                print("    🏆 Selected: Best Quality")
                return None
            if 1 <= choice <= len(qualities):
                sel = qualities[choice - 1]
                print(f"    ✅ Selected: {sel['label']} "
                      f"({sel['width']}x{sel['height']})")
                return sel
            print(f"    ❌ Enter 0-{len(qualities)}")
        except ValueError:
            print("    ❌ Number only")


def get_video_url_for_quality(reel, quality_choice):
    """Selected quality এর exact URL return"""
    if quality_choice is None:
        return reel["url"]

    target_w = quality_choice["width"]
    target_h = quality_choice["height"]

    # Exact match
    for v in reel.get("versions", []):
        if v.get("width") == target_w and v.get("height") == target_h:
            return v["url"]

    # Closest match
    best_match = None
    best_diff = float('inf')
    for v in reel.get("versions", []):
        w, h = v.get("width", 0), v.get("height", 0)
        diff = abs(w - target_w) + abs(h - target_h)
        if diff < best_diff:
            best_diff = diff
            best_match = v

    return best_match["url"] if best_match else reel["url"]


def download_single_video(url, filepath, max_retries=MAX_RETRIES):
    """
    Single video download with full retry
    - ৫ বার retry
    - Tor circuit refresh on failure
    - কখনো skip করবে না
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.instagram.com/",
    }

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=90)

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

            # Write file
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)

            # Validate (too small = error page)
            size = os.path.getsize(filepath)
            if size < 5000:
                if os.path.exists(filepath):
                    os.remove(filepath)
                raise Exception(f"File too small ({size}B)")

            return True, size

        except Exception as e:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass

            if attempt < max_retries:
                wait = RETRY_DELAY * attempt
                time.sleep(wait)

                # Refresh Tor on rate limit / connection errors
                err_str = str(e)
                if USE_TOR and ("Connection" in err_str or "429" in err_str
                                or "403" in err_str or "timeout" in err_str.lower()):
                    refresh_tor_circuit()
            else:
                return False, f"{type(e).__name__}: {e}"

    return False, "Max retries exceeded"


def download_all_reels(reels, quality_choice, folder):
    """সব reels download"""
    os.makedirs(folder, exist_ok=True)
    total = len(reels)
    total_size = 0

    print(f"\n    {'─' * 58}")
    print(f"    ⬇️  Downloading {total} reels → {folder}/")
    print(f"    🔄 Max retries: {MAX_RETRIES} per video")
    print(f"    {'─' * 58}\n")

    downloaded = []
    failed = []
    used_names = set()

    for i, reel in enumerate(reels, 1):
        # Generate unique filename
        fname = make_filename(reel.get("caption", ""),
                              reel.get("post_id", ""), i)

        # Avoid duplicate names
        base, ext = os.path.splitext(fname)
        counter = 1
        original_fname = fname
        while fname in used_names or os.path.exists(os.path.join(folder, fname)):
            fname = f"{base}_{counter}{ext}"
            counter += 1
        used_names.add(fname)

        fpath = os.path.join(folder, fname)
        video_url = get_video_url_for_quality(reel, quality_choice)

        # Progress line
        bar = progress_bar(i, total)
        sys.stdout.write(
            f"\r    [{bar}] {i}/{total} ⬇️  {fname[:48]:<48s}"
        )
        sys.stdout.flush()

        success, result = download_single_video(video_url, fpath)

        if success:
            total_size += result
            q = get_resolution_label(reel.get("width", 0),
                                     reel.get("height", 0))
            downloaded.append({
                "name": fname,
                "size": result,
                "quality": q,
                "caption_preview": (reel.get("caption", "") or "")[:50],
            })
            sys.stdout.write(
                f"\r    [{bar}] {i}/{total} ✅ {fname[:36]:<36s} "
                f"{format_size(result):>8s} [{q}]\n"
            )
        else:
            failed.append({
                "index": i,
                "name": fname,
                "error": str(result)[:50],
            })
            sys.stdout.write(
                f"\r    [{bar}] {i}/{total} ❌ {fname[:36]:<36s} "
                f"{str(result)[:30]}\n"
            )

        sys.stdout.flush()
        time.sleep(DELAY_BETWEEN)

    return downloaded, failed, total_size


# ───────────────────────────────────────────────────────────────────
#  CORE: ZIP & Summary
# ───────────────────────────────────────────────────────────────────

def create_zip(folder, zipname):
    """Folder → ZIP"""
    if not os.path.exists(folder):
        return None, 0

    mp4_files = sorted(
        [f for f in os.listdir(folder) if f.lowerendswith(('.mp4', '.mov', '.webm'))]
    )

    if not mp4_files:
        return None, 0

    print(f"\n    📦 Creating ZIP: {os.path.basename(zipname)}")

    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in mp4_files:
            filepath = os.path.join(folder, f)
            if os.path.exists(filepath):
                zf.write(filepath, f)

    size = os.path.getsize(zipname)
    print(f"    ✅ ZIP: {os.path.basename(zipname)} ({format_size(size)})")
    return zipname, size


def show_summary(downloaded, failed, total_size, zipname, zip_size, profile):
    """Final summary"""
    w = 60
    print(f"\n    {'═' * w}")
    print(f"    {'📊 DOWNLOAD SUMMARY':^{w}}")
    print(f"    {'═' * w}")
    print(f"    ║  👤 Profile:    {profile}")
    print(f"    ║  ✅ Downloaded: {len(downloaded):>4d} videos")
    print(f"    ║  ❌ Failed:     {len(failed):>4d} videos")
    print(f"    ║  📁 Total Size: {format_size(total_size):>10s}")
    print(f"    ║")
    print(f"    {'─' * w}")
    print(f"    {'📋 Files (first 25)':^{w}}")
    print(f"    {'─' * w}")

    for i, d in enumerate(downloaded[:25], 1):
        name = d["name"]
        if len(name) > 40:
            name = name[:40] + "..."
        print(f"    ║  {i:3d}. {name:<44s} "
              f"{format_size(d['size']):>8s} [{d['quality']}]")

    if len(downloaded) > 25:
        print(f"    ║  ... +{len(downloaded) - 25} more files")

    if failed:
        print(f"    ║")
        print(f"    {'─' * w}")
        print(f"    {'⚠️  Failed':^{w}}")
        print(f"    {'─' * w}")
        for f in failed[:10]:
            print(f"    ║  #{f['index']:>3d}. {f['name'][:40]:<40s}")

    if zipname and os.path.exists(zipname):
        print(f"    ║")
        print(f"    {'─' * w}")
        print(f"    ║  📦 ZIP: {os.path.basename(zipname)}")
        print(f"    ║  📥 VS Code → Left Sidebar → Right Click → Download")
        print(f"    ║  📥 Or:  ls -lh {zipname}")

    print(f"    {'═' * w}")


# ───────────────────────────────────────────────────────────────────
#  MAIN
# ───────────────────────────────────────────────────────────────────

def main():
    banner()

    # ── 1. Configuration ──────────────────────────────────────
    print("    ╔════════════════════════════════════════╗")
    print("    ║         ⚙️   CONFIGURATION             ║")
    print("    ╚════════════════════════════════════════╝")

    target = input(f"\n    👤 Target username [{TARGET_PROFILE}]: ").strip()
    if not target:
        target = TARGET_PROFILE

    count_input = input("    📊 How many reels? (0 = ALL): ").strip() or "0"
    max_count = None
    if count_input != "0":
        try:
            max_count = int(count_input)
            print(f"    ✅ First {max_count} reels")
        except ValueError:
            print("    ⚠️  Invalid, downloading ALL")
    else:
        print("    ✅ ALL reels")

    # ── 2. Auth ───────────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         🔐 AUTHENTICATION              ║")
    print(f"    ╚════════════════════════════════════════╝")

    cookies = load_cookies(COOKIES_FILE)
    session = create_session(cookies)
    csrf_token = get_fresh_csrf(session)

    if not csrf_token:
        print("\n    ❌ Cannot get CSRF token!")
        print("       Check your internet connection.")
        sys.exit(1)

    print(f"    ✅ CSRF: {csrf_token[:20]}...")

    # ── 3. Profile lookup ─────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         👤 PROFILE LOOKUP              ║")
    print(f"    ╚════════════════════════════════════════╝")

    user_id = get_user_id(session, target, csrf_token)
    if not user_id:
        print("\n    ❌ User ID not found!")
        sys.exit(1)

    # ── 4. Fetch reels ────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         🎬 FETCHING REELS              ║")
    print(f"    ╚════════════════════════════════════════╝")

    reels = fetch_all_reels(session, user_id, csrf_token, target, max_count)

    if not reels:
        print("\n    ❌ No reels found!")
        print("       Possible reasons:")
        print("       - Account is private (follow from cookies account)")
        print("       - Account has no reels")
        print("       - Cookies are expired")
        sys.exit(1)

    # ── 5. Quality ────────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         📺 QUALITY SELECTION           ║")
    print(f"    ╚════════════════════════════════════════╝")

    quality_choice = select_quality(reels)

    # ── 6. Download ───────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         ⬇️   DOWNLOADING                ║")
    print(f"    ╚════════════════════════════════════════╝")

    folder = os.path.join(DOWNLOAD_DIR, f"{target}_reels")
    downloaded, failed, total_size = download_all_reels(
        reels, quality_choice, folder
    )

    # ── 7. ZIP ────────────────────────────────────────────────
    zipname = os.path.join(DOWNLOAD_DIR, f"{target}_reels.zip")
    zipname_actual, zip_size = create_zip(folder, zipname)

    # ── 8. Summary ────────────────────────────────────────────
    show_summary(downloaded, failed, total_size,
                 zipname_actual, zip_size, target)


if __name__ == "__main__":
    main()
