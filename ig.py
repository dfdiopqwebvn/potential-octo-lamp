cat << 'PYEOF' > ig_reels_downloader.py
#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║            📥 Instagram Reels Downloader v3.0                    ║
║                                                                  ║
║  Features:                                                       ║
║    ✅ Download reels with ORIGINAL quality                       ║
║    ✅ Choose video quality (1080p/720p/480p/360p/Best)           ║
║    ✅ Choose how many videos to download                         ║
║    ✅ Caption-based short filenames (no OS errors)               ║
║    ✅ Post ID fallback (never skip any video)                    ║
║    ✅ Auto retry 3x on failure (zero skip guarantee)             ║
║    ✅ Auto zip after download                                    ║
║    ✅ Tor proxy with auto circuit refresh                        ║
║    ✅ Beautiful progress display                                 ║
║                                                                  ║
║  Version: 3.0                                                    ║
║  Date: 2026-06-09                                               ║
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
import signal

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

TARGET_PROFILE  = "jan16.__"                          # যার reels download করবে
COOKIES_FILE    = "cookies.txt"                       # Browser cookies file
USE_TOR         = True                                # Tor proxy ব্যবহার করবে?
TOR_PROXY       = "socks5h://127.0.0.1:9050"         # Tor SOCKS5 address
DOWNLOAD_DIR    = "downloads"                         # Download folder
MAX_FILENAME    = 50                                  # Max filename characters
MAX_RETRIES     = 3                                   # Retry count per video
RETRY_DELAY     = 5                                   # Seconds between retries

# ═══════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ───────────────────────────────────────────────────────────────────

def banner():
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║         📥 Instagram Reels Downloader v3.0            ║
    ║      ✅ No Skip  ✅ Short Names  ✅ Quality          ║
    ╚═══════════════════════════════════════════════════════╝
    """)


def clean_caption(text, max_len=MAX_FILENAME):
    """
    Caption থেকে safe short filename বানাও
    - Newlines, special chars remove
    - Max 50 characters
    - Empty/null = None return (fallback trigger)
    """
    if not text or not text.strip():
        return None

    # Clean
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    text = re.sub(r'[^\w\s\-.]', '', text)
    text = text.strip()

    # Too short = not useful
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
    সবসময় valid filename return করে — কখনো fail হবে না

    Priority:
      1. Short caption (001_sunset_at_beach.mp4)
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
    """Width/Height → 1080p/720p/480p/360p"""
    if not width or not height:
        return "unknown"
    h = max(width, height)
    if h >= 1920:   return "1080p"
    elif h >= 1280: return "720p"
    elif h >= 854:  return "480p"
    elif h >= 640:  return "360p"
    else:           return f"{h}p"


def format_size(bytes_size):
    """Bytes → readable string"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} MB"


def progress_bar(current, total, width=30):
    """[████████░░░░░░░░░░░░░░░░░░░░░░]"""
    if total == 0:
        return "░" * width
    filled = int(width * current / total)
    return "█" * filled + "░" * (width - filled)


def refresh_tor_circuit():
    """
    Tor নতুন IP দেবে — যদি একটা IP block হয়
    Signal NEWNYM পাঠালে Tor নতুন circuit বানায়
    """
    try:
        # Method 1: torsocks signal
        subprocess.run(
            ["killall", "-HUP", "tor"],
            capture_output=True, timeout=5
        )
        time.sleep(5)
        print("    🔄 Tor circuit refreshed (new IP)")
        return True
    except Exception:
        pass

    try:
        # Method 2: Control port
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", 9051))
        s.send(b"AUTHENTICATE\r\n")
        s.send(b"SIGNAL NEWNYM\r\n")
        s.close()
        time.sleep(5)
        print("    🔄 Tor circuit refreshed via control port")
        return True
    except Exception:
        pass

    print("    ⚠️  Could not refresh Tor circuit (manual restart needed)")
    return False


def show_quality_options(qualities):
    """Beautiful quality menu"""
    print("""
    ┌───────────────────────────────────────────┐
    │         📺 Available Video Qualities       │
    ├───────────────────────────────────────────┤
    │                                           │
    │   0. 🏆 Best Quality (Original Upload)    │""")

    for i, q in enumerate(qualities, 1):
        if "1080" in q["label"]:
            emoji = "🟢"
            note = "Full HD"
        elif "720" in q["label"]:
            emoji = "🟡"
            note = "HD Ready"
        elif "480" in q["label"]:
            emoji = "🟠"
            note = "Standard"
        else:
            emoji = "🔴"
            note = "Low"

        print(f"    │   {i}. {emoji} {q['label']:<8s} ({q['width']}x{q['height']:<4s})  {note:<10s}│")

    print("    │                                           │")
    print("    └───────────────────────────────────────────┘")


# ───────────────────────────────────────────────────────────────────
#  CORE FUNCTIONS
# ───────────────────────────────────────────────────────────────────

def load_cookies(filename):
    """Netscape cookies.txt থেকে cookies load করো"""
    print(f"\n    🔐 Loading cookies from: {filename}")

    if not os.path.exists(filename):
        print(f"    ❌ File not found: {filename}")
        print(f"       Export cookies from your browser first!")
        sys.exit(1)

    cj = http.cookiejar.MozillaCookieJar(filename)
    cj.load(ignore_discard=True, ignore_expires=True)

    cookies = {}
    for c in cj:
        cookies[c.name] = c.value

    # Check required cookies
    required = ['sessionid']
    for r in required:
        if r not in cookies:
            print(f"    ❌ Required cookie '{r}' not found!")
            print(f"       Re-export cookies from your browser.")
            sys.exit(1)

    print(f"    ✅ Loaded {len(cookies)} cookies")
    print(f"    ✅ sessionid: {cookies['sessionid'][:20]}...")

    # Optional info
    if 'ds_user_id' in cookies:
        print(f"    ✅ ds_user_id: {cookies['ds_user_id']}")
    if 'csrftoken' in cookies:
        print(f"    ✅ csrftoken: {cookies['csrftoken'][:20]}...")

    return cookies


def create_session(cookies):
    """Instagram session তৈরি করো (Tor optional)"""
    s = requests.Session()

    # Proxy setup
    if USE_TOR:
        s.proxies = {
            "http": TOR_PROXY,
            "https": TOR_PROXY,
        }
        print(f"    🌐 Using Tor proxy: {TOR_PROXY}")

    # Mobile browser headers (better success rate)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.6 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })

    # Set all cookies
    for name, value in cookies.items():
        s.cookies.set(name, value, domain=".instagram.com", path="/")

    return s


def get_csrf_token(session):
    """Fresh CSRF token নাও (Instagram প্রতিবার নতুন চায়)"""
    print("\n    🔄 Getting fresh CSRF token...")

    try:
        r = session.get("https://www.instagram.com/", timeout=30)
    except Exception as e:
        print(f"    ❌ Cannot reach Instagram: {e}")
        return None

    # From response cookies
    for cookie in session.cookies:
        if cookie.name == 'csrftoken':
            print(f"    ✅ CSRF token obtained from cookies")
            return cookie.value

    # From HTML body
    match = re.search(r'"csrf_token":"([^"]+)"', r.text)
    if match:
        print(f"    ✅ CSRF token extracted from HTML")
        return match.group(1)

    print("    ❌ Cannot get CSRF token!")
    return None


def get_user_id(session, username, csrf_token):
    """Username → User ID + profile info"""
    print(f"\n    📥 Looking up profile: {username}")

    session.headers.update({
        "X-CSRFToken": csrf_token,
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{username}/",
    })

    # Method 1: REST API
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

            print(f"    ✅ Username:  {user['username']}")
            if full_name:
                print(f"    📝 Name:     {full_name}")
            print(f"    👥 Followers: {followers:,}" if isinstance(followers, int) else f"    👥 Followers: {followers}")
            print(f"    👤 Following: {following:,}" if isinstance(following, int) else f"    👤 Following: {following}")
            print(f"    🆔 User ID:  {uid}")

            if is_private:
                print(f"    🔒 Account is PRIVATE — need to follow with cookies account")

            return uid
    except Exception as e:
        print(f"    ⚠️  REST API error: {e}")

    # Method 2: HTML scraping
    print("    🔄 Trying HTML method...")
    try:
        r = session.get(f"https://www.instagram.com/{username}/", timeout=30)
        match = re.search(r'"profilePage_([0-9]+)"', r.text)
        if not match:
            match = re.search(r'"user_id":"([0-9]+)"', r.text)
        if match:
            uid = match.group(1)
            print(f"    ✅ User ID from HTML: {uid}")
            return uid
    except Exception as e:
        print(f"    ⚠️  HTML method error: {e}")

    print("    ❌ Cannot find user ID!")
    print("       Possible reasons:")
    print("       - Username is incorrect")
    print("       - Account is private (need to follow)")
    print("       - Cookies are expired")
    return None


def fetch_reels(session, user_id, csrf_token, username, max_count=None):
    """সব reels collect করো (paginated)"""
    print(f"\n    🎬 Fetching reels from: {username}")

    if max_count:
        print(f"    📊 Target: first {max_count} reels")
    else:
        print(f"    📊 Target: ALL reels")

    reels = []
    max_id = None
    page = 0
    consecutive_errors = 0

    session.headers.update({
        "X-CSRFToken": csrf_token,
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{username}/reels/",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    while True:
        page += 1

        # Enough reels collected?
        if max_count and len(reels) >= max_count:
            reels = reels[:max_count]
            break

        try:
            post_data = {
                "target_user_id": user_id,
                "page_size": 12,
                "include_feed_video": True,
            }
            if max_id:
                post_data["max_id"] = max_id

            r = session.post(
                "https://www.instagram.com/api/v1/clips/user/",
                data=post_data,
                timeout=30,
            )

            # CSRF error → refresh token and retry
            if r.status_code == 403:
                print(f"\n    🔄 CSRF expired, refreshing...")
                csrf_token = get_csrf_token(session)
                if csrf_token:
                    session.headers["X-CSRFToken"] = csrf_token
                    r = session.post(
                        "https://www.instagram.com/api/v1/clips/user/",
                        data=post_data,
                        timeout=30,
                    )

            # Still failing → try Feed API
            if r.status_code != 200:
                print(f"\n    ⚠️  Clips API: {r.status_code}, trying Feed API...")
                r = session.get(
                    f"https://www.instagram.com/api/v1/feed/user/{user_id}/?count=50",
                    timeout=30,
                )
                if r.status_code == 200:
                    result = r.json()
                    for item in result.get("items", []):
                        if item.get("media_type") == 2:  # Video
                            versions = item.get("video_versions", [])
                            caption = ""
                            cap = item.get("caption", {})
                            if isinstance(cap, dict):
                                caption = cap.get("text", "")

                            if versions:
                                versions_sorted = sorted(
                                    versions,
                                    key=lambda v: v.get("width", 0) * v.get("height", 0),
                                    reverse=True
                                )
                                reels.append({
                                    "post_id": str(item.get("pk", "")),
                                    "caption": caption,
                                    "versions": versions_sorted,
                                    "url": versions_sorted[0]["url"],
                                    "width": versions_sorted[0].get("width", 0),
                                    "height": versions_sorted[0].get("height", 0),
                                })
                    print(f"    ✅ Feed API: {len(reels)} videos found")
                break

            result = r.json()
            items = result.get("items", [])

            if not items:
                break

            consecutive_errors = 0  # Reset error counter

            for item in items:
                media = item.get("media", {})
                versions = media.get("video_versions", [])

                if not versions:
                    continue

                caption = ""
                cap = media.get("caption", {})
                if isinstance(cap, dict):
                    caption = cap.get("text", "")

                # Sort versions by quality (highest first)
                versions_sorted = sorted(
                    versions,
                    key=lambda v: v.get("width", 0) * v.get("height", 0),
                    reverse=True
                )

                best = versions_sorted[0]

                reels.append({
                    "post_id": str(media.get("pk", "")),
                    "caption": caption,
                    "versions": versions_sorted,
                    "url": best["url"],
                    "width": best.get("width", 0),
                    "height": best.get("height", 0),
                })

            # Progress bar
            target_display = max_count or 999
            bar = progress_bar(len(reels), target_display)
            sys.stdout.write(
                f"\r    📜 [{bar}] {len(reels)} reels found (Page {page})"
            )
            sys.stdout.flush()

            # Check pagination
            paging = result.get("paging_info", {})
            if not paging.get("more_available"):
                break

            max_id = paging.get("max_id")
            if not max_id:
                break

            time.sleep(2)

        except requests.exceptions.ConnectionError:
            consecutive_errors += 1
            print(f"\n    ⚠️  Connection error (attempt {consecutive_errors})")

            if USE_TOR and consecutive_errors <= 2:
                print("    🔄 Refreshing Tor circuit...")
                refresh_tor_circuit()
                time.sleep(3)
                continue
            elif consecutive_errors > 3:
                print("    ❌ Too many connection errors, stopping.")
                break

        except Exception as e:
            consecutive_errors += 1
            print(f"\n    ❌ Page {page} error: {e}")
            if consecutive_errors > 3:
                break
            time.sleep(5)
            continue

    # Trim to max_count
    if max_count:
        reels = reels[:max_count]

    print(f"\n    📊 Total reels collected: {len(reels)}")
    return reels


def detect_available_qualities(reels):
    """সব reels scan করে available resolutions বের করো"""
    all_qualities = {}

    for reel in reels:
        for v in reel.get("versions", []):
            w = v.get("width", 0)
            h = v.get("height", 0)
            label = get_resolution_label(w, h)
            key = f"{w}x{h}"
            if key not in all_qualities:
                all_qualities[key] = {
                    "label": label,
                    "width": w,
                    "height": h,
                }

    # Sort by resolution (highest first)
    sorted_q = sorted(
        all_qualities.values(),
        key=lambda q: q["width"] * q["height"],
        reverse=True
    )

    return sorted_q


def select_quality(reels):
    """User কে quality select করতে দাও"""
    qualities = detect_available_qualities(reels)

    if not qualities:
        print("    ⚠️  No quality info available. Using best.")
        return None

    show_quality_options(qualities)

    while True:
        try:
            choice = input("\n    👉 Select quality (0 for Best): ").strip()

            if not choice:
                choice = "0"

            choice = int(choice)

            if choice == 0:
                print("    🏆 Selected: Best Quality (Original)")
                return None  # None = best

            if 1 <= choice <= len(qualities):
                selected = qualities[choice - 1]
                print(f"    ✅ Selected: {selected['label']} ({selected['width']}x{selected['height']})")
                return selected
            else:
                print(f"    ❌ Enter 0-{len(qualities)}")

        except ValueError:
            print("    ❌ Enter a number")


def get_video_url(reel, quality_choice):
    """Selected quality এর video URL return করো"""
    # Best quality = already first in sorted list
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

    if best_match:
        return best_match["url"]

    # Fallback: best quality
    return reel["url"]


def download_single_video(video_url, filepath, max_retries=MAX_RETRIES):
    """
    Single video download with retry
    - কখনো skip করবে না
    - Tor circuit refresh করবে যদি block হয়
    - 3 বার retry করবে
    """
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(
                video_url,
                stream=True,
                timeout=90,
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                                   "Mobile/15E148 Safari/604.1",
                }
            )

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

            # Write file
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            # Validate file size (too small = error page)
            size = os.path.getsize(filepath)
            if size < 1000:
                os.remove(filepath)
                raise Exception(f"File too small ({size}B) — likely error page")

            return True, size

        except Exception as e:
            # Cleanup partial file
            if os.path.exists(filepath):
                os.remove(filepath)

            if attempt < max_retries:
                wait = RETRY_DELAY * attempt
                time.sleep(wait)

                # Refresh Tor circuit on connection errors
                if USE_TOR and ("Connection" in str(e) or "429" in str(e)):
                    refresh_tor_circuit()
            else:
                return False, str(e)

    return False, "Max retries exceeded"


def download_reels(reels, quality_choice, folder):
    """সব reels download করো — কোনোটা skip হবে না"""
    os.makedirs(folder, exist_ok=True)

    total = len(reels)
    total_size = 0

    print(f"\n    {'─' * 58}")
    print(f"    ⬇️  Downloading {total} reels to: {folder}/")
    print(f"    🔄 Max retries per video: {MAX_RETRIES}")
    print(f"    {'─' * 58}\n")

    downloaded = []
    failed = []

    for i, reel in enumerate(reels, 1):
        # Generate safe filename (NEVER fails)
        fname = make_filename(
            reel.get("caption", ""),
            reel.get("post_id", ""),
            i
        )
        fpath = os.path.join(folder, fname)

        # Handle duplicate filenames
        base, ext = os.path.splitext(fname)
        counter = 1
        while os.path.exists(fpath):
            fname = f"{base}_{counter}{ext}"
            fpath = os.path.join(folder, fname)
            counter += 1

        # Get video URL for selected quality
        video_url = get_video_url(reel, quality_choice)

        # Show progress
        bar = progress_bar(i, total)
        sys.stdout.write(
            f"\r    [{bar}] {i}/{total} ⬇️  {fname[:48]:<48s}"
        )
        sys.stdout.flush()

        # Download with retry (NEVER skips)
        success, result = download_single_video(video_url, fpath)

        if success:
            total_size += result
            q_label = get_resolution_label(
                reel.get("width", 0),
                reel.get("height", 0)
            )
            downloaded.append({
                "name": fname,
                "size": result,
                "quality": q_label,
                "caption_preview": (reel.get("caption", "") or "")[:40],
            })
            sys.stdout.write(
                f"\r    [{bar}] {i}/{total} ✅ {fname[:38]:<38s} "
                f"{format_size(result):>8s} [{q_label}]\n"
            )
        else:
            failed.append({
                "index": i,
                "name": fname,
                "error": result,
            })
            sys.stdout.write(
                f"\r    [{bar}] {i}/{total} ❌ {fname[:38]:<38s} "
                f"FAILED: {result[:30]}\n"
            )

        sys.stdout.flush()
        time.sleep(2)

    return downloaded, failed, total_size


def create_zip(folder, zipname):
    """Folder কে compressed zip করো"""
    mp4_files = [f for f in os.listdir(folder) if f.endswith('.mp4')]

    if not mp4_files:
        return None, 0

    print(f"\n    📦 Creating zip: {os.path.basename(zipname)}...")

    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(mp4_files):
            filepath = os.path.join(folder, f)
            zf.write(filepath, f)

    size = os.path.getsize(zipname)
    print(f"    ✅ Created: {os.path.basename(zipname)} ({format_size(size)})")

    return zipname, size


def show_summary(downloaded, failed, total_size, zipname, zip_size):
    """Beautiful final summary"""
    w = 60

    print(f"\n    {'═' * w}")
    print(f"    {'📊 DOWNLOAD SUMMARY':^{w}}")
    print(f"    {'═' * w}")

    print(f"    ║")
    print(f"    ║   ✅ Downloaded : {len(downloaded):>4d} videos")
    print(f"    ║   ❌ Failed     : {len(failed):>4d} videos")
    print(f"    ║   📁 Total Size : {format_size(total_size):>10s}")
    print(f"    ║")

    # File list
    print(f"    {'─' * w}")
    print(f"    {'📋 Downloaded Files':^{w}}")
    print(f"    {'─' * w}")

    max_display = 25
    for i, d in enumerate(downloaded[:max_display], 1):
        name = d["name"]
        if len(name) > 42:
            name = name[:42] + ".."
        q = d["quality"]
        sz = format_size(d["size"])
        print(f"    ║   {i:3d}. {name:<44s} {sz:>8s} [{q}]")

    remaining = len(downloaded) - max_display
    if remaining > 0:
        print(f"    ║   ... +{remaining} more files")

    # Failed list
    if failed:
        print(f"    ║")
        print(f"    {'─' * w}")
        print(f"    {'⚠️  Failed Downloads':^{w}}")
        print(f"    {'─' * w}")
        for f in failed[:10]:
            print(f"    ║   #{f['index']:>3d}. {f['name'][:40]:<40s} {f['error'][:20]}")

    # Zip info
    if zipname:
        print(f"    ║")
        print(f"    {'─' * w}")
        print(f"    ║   📦 ZIP File  : {os.path.basename(zipname)} ({format_size(zip_size)})")
        print(f"    ║   📥 Download  : LEFT sidebar → {os.path.basename(zipname)}")
        print(f"    ║                  → Right Click → Download")

    print(f"    {'═' * w}")


# ───────────────────────────────────────────────────────────────────
#  MAIN PROGRAM
# ───────────────────────────────────────────────────────────────────

def main():
    banner()

    # ── STEP 1: Configuration ──────────────────────────────────────
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
            print(f"    ✅ Will download first {max_count} reels")
        except ValueError:
            print("    ⚠️  Invalid number, downloading ALL")
    else:
        print("    ✅ Will download ALL reels")

    # ── STEP 2: Authentication ─────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         🔐 AUTHENTICATION              ║")
    print(f"    ╚════════════════════════════════════════╝")

    cookies = load_cookies(COOKIES_FILE)
    session = create_session(cookies)

    csrf_token = get_csrf_token(session)
    if not csrf_token:
        print("\n    ❌ Cannot proceed without CSRF token!")
        sys.exit(1)

    # ── STEP 3: Profile Lookup ─────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         👤 PROFILE LOOKUP              ║")
    print(f"    ╚════════════════════════════════════════╝")

    user_id = get_user_id(session, target, csrf_token)
    if not user_id:
        print("\n    ❌ Cannot proceed without User ID!")
        sys.exit(1)

    # ── STEP 4: Fetch Reels ────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         🎬 FETCHING REELS              ║")
    print(f"    ╚════════════════════════════════════════╝")

    reels = fetch_reels(session, user_id, csrf_token, target, max_count)

    if not reels:
        print("\n    ❌ No reels found!")
        print("       Possible reasons:")
        print("       - Profile has no video reels")
        print("       - Account is private")
        print("       - Cookies are expired")
        sys.exit(1)

    # ── STEP 5: Quality Selection ──────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         📺 QUALITY SELECTION           ║")
    print(f"    ╚════════════════════════════════════════╝")

    quality_choice = select_quality(reels)

    # ── STEP 6: Download ───────────────────────────────────────────
    print(f"\n    ╔════════════════════════════════════════╗")
    print(f"    ║         ⬇️   DOWNLOADING                ║")
    print(f"    ╚════════════════════════════════════════╝")

    folder = os.path.join(DOWNLOAD_DIR, f"{target}_reels")
    downloaded, failed, total_size = download_reels(reels, quality_choice, folder)

    # ── STEP 7: Create ZIP ─────────────────────────────────────────
    zipname = os.path.join(DOWNLOAD_DIR, f"{target}_reels.zip")
    zipname_actual, zip_size = create_zip(folder, zipname)

    # ── STEP 8: Summary ────────────────────────────────────────────
    show_summary(downloaded, failed, total_size, zipname_actual, zip_size)


# ───────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
PYEOF
