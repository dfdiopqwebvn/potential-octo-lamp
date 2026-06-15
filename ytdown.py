#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          📺 YouTube Video Downloader · v3.0                  ║
║          yt_youtube_downloader.py                            ║
║                                                              ║
║  • Single video / playlist / channel                        ║
║  • Quality picker (Best / 1080p / 720p / 480p / 360p)       ║
║  • Format picker (MP4 / MKV / WebM / MP3 / M4A)             ║
║  • Subtitle / CC download                                   ║
║  • Thumbnail + metadata embedding                           ║
║  • Smart title-based filenames                              ║
║  • 3-attempt retry with backoff                             ║
║  • HTTP / SOCKS5 proxy support                              ║
║  • Auto-ZIP when finished                                   ║
║  • Interactive CLI                                          ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import shutil
import subprocess
import zipfile
import time
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yt_dlp
    # Force-update yt-dlp to latest version (YouTube changes daily)
    # Check: if older than 7 days OR known-bad versions, upgrade.
    try:
        from yt_dlp.version import __version__ as _ytdlp_ver
        import datetime as _dt
        # yt-dlp versions: 2024.10.22.232152 etc. Compare date prefix.
        _ver_str = str(_ytdlp_ver)
        _ver_date = _ver_str.split(".")[0:3]
        if len(_ver_date) == 3 and _ver_date[0].isdigit():
            _ytdlp_age_days = None
            try:
                _ytdlp_date = _dt.date(int(_ver_date[0]), int(_ver_date[1]), int(_ver_date[2]))
                _ytdlp_age_days = (_dt.date.today() - _ytdlp_date).days
            except Exception:
                pass
            if _ytdlp_age_days is None or _ytdlp_age_days > 7:
                print(f"⚠️  yt-dlp {_ytdlp_ver} is {(_ytdlp_age_days or '?')} days old. Updating to latest…")
                for _upd in [
                    [sys.executable, "-m", "pip", "install", "--user", "-U", "-q", "yt-dlp[default]"],
                    [sys.executable, "-m", "pip", "install", "-U", "-q", "yt-dlp[default]"],
                    ["pip3", "install", "--user", "-U", "-q", "yt-dlp[default]"],
                    ["pip3", "install", "-U", "-q", "yt-dlp[default]"],
                ]:
                    try:
                        subprocess.check_call(_upd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        print("✅ yt-dlp updated. Restarting script…")
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                    except Exception:
                        continue
    except Exception:
        pass  # version check is best-effort
except ImportError:
    print("❌ yt-dlp not found. Trying to install...")
    installed = False

    # Add ~/.local/bin to PATH (Cloud Shell, Linux user installs)
    local_bin = os.path.expanduser("~/.local/bin")
    if os.path.isdir(local_bin) and local_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")

    # Try multiple install strategies
    # Use yt-dlp[default] to get curl_cffi for YouTube impersonation
    install_attempts = [
        [sys.executable, "-m", "pip", "install", "--user", "-q", "yt-dlp[default]"],
        [sys.executable, "-m", "pip", "install", "--user", "-q", "yt-dlp"],
        [sys.executable, "-m", "pip", "install", "-q", "yt-dlp[default]"],
        ["pip3", "install", "--user", "-q", "yt-dlp[default]"],
        ["pip3", "install", "--user", "-q", "yt-dlp"],
        ["pip3", "install", "-q", "yt-dlp"],
        ["pip", "install", "--user", "-q", "yt-dlp"],
    ]
    for cmd in install_attempts:
        try:
            print(f"   ↪ {' '.join(cmd)}")
            subprocess.check_call(cmd)
            installed = True
            break
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue

    if not installed:
        print("\n❌ Auto-install failed. Run one of these manually:")
        print("   pip3 install --user 'yt-dlp[default]'")
        print("   python3 -m pip install --user 'yt-dlp[default]'")
        print("   # Or use a virtual env:")
        print("   python3 -m venv venv && source venv/bin/activate && pip install 'yt-dlp[default]'")
        sys.exit(1)

    # Re-execute script so the new module is importable
    print("✅ yt-dlp installed. Restarting script...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ═══════════════════════════════════════════════════════════
# 🎬  FFMPEG DETECTION (needed for merging video + audio)
# ═══════════════════════════════════════════════════════════

def has_ffmpeg():
    """Check whether ffmpeg is on PATH. Returns the path string or None."""
    return shutil.which("ffmpeg")


def try_install_ffmpeg():
    """Best-effort ffmpeg installer. Works on Linux/macOS. Skips on Windows."""
    if has_ffmpeg():
        return True
    print("⚠️  ffmpeg not found. Trying to install…")
    is_windows = sys.platform.startswith("win")
    is_macos = sys.platform == "darwin"
    cmds = []
    if is_macos:
        cmds = [["brew", "install", "ffmpeg"]]
    elif not is_windows:
        # Linux — try apt, then dnf, then yum
        cmds = [
            ["sudo", "apt", "update"],
            ["sudo", "apt", "install", "-y", "ffmpeg"],
            ["sudo", "dnf", "install", "-y", "ffmpeg"],
            ["sudo", "yum", "install", "-y", "ffmpeg"],
        ]
    else:
        print("   ℹ️  Windows detected. Please install ffmpeg manually:")
        print("      Download: https://www.gyan.dev/ffmpeg/builds/")
        print("      Extract, then add C:\\\\ffmpeg\\\\bin to your PATH.")
        return False
    for cmd in cmds:
        try:
            print(f"   ↪ {' '.join(cmd)}")
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        if has_ffmpeg():
            print("✅ ffmpeg installed successfully.")
            return True
    return False


FFMPEG_AVAILABLE = bool(has_ffmpeg())
if not FFMPEG_AVAILABLE:
    # Last-ditch: try once at startup so users don't have to do it manually
    try_install_ffmpeg()
    FFMPEG_AVAILABLE = bool(has_ffmpeg())

    # Also recommend installing a JS runtime (deno) for best YouTube extraction
    print("💡 Tip: For best results install a JS runtime:")
    print("   • deno  : curl -fsSL https://deno.land/install.sh | sh")
    print("   • nodejs: https://nodejs.org/")


def try_install_nodejs():
    """Best-effort Node.js installer (needed for YouTube JS challenge solver)."""
    if shutil.which("node"):
        return True
    print("⚠️  Node.js not found. YouTube requires a JS runtime for challenge solving.")
    print("   Trying to install…")
    is_windows = sys.platform.startswith("win")
    is_macos = sys.platform == "darwin"
    cmds = []
    if is_macos:
        cmds = [["brew", "install", "node"]]
    elif not is_windows:
        cmds = [
            ["sudo", "apt", "update"],
            ["sudo", "apt", "install", "-y", "nodejs"],
            ["sudo", "dnf", "install", "-y", "nodejs"],
            ["sudo", "yum", "install", "-y", "nodejs"],
        ]
    for cmd in cmds:
        try:
            print(f"   ↪ {' '.join(cmd)}")
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        if shutil.which("node"):
            print("✅ Node.js installed successfully.")
            return True
    # Fallback: try deno
    try:
        subprocess.check_call(
            ["curl", "-fsSL", "https://deno.land/install.sh", "|", "sh"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if shutil.which("deno"):
            print("✅ Deno installed successfully.")
            return True
    except Exception:
        pass
    print("⚠️  Could not auto-install Node.js/Deno. YouTube JS challenges may fail.")
    print("   → Install manually: https://nodejs.org/ or https://deno.land/")
    return False


# ═══════════════════════════════════════════════════════════
# 🔍  ENVIRONMENT DIAGNOSTICS
# ═══════════════════════════════════════════════════════════

# Known data-center / cloud IP hostnames (Cloud Shell, AWS, GCP, Azure, etc.)
# YouTube heavily rate-limits / blocks these. Used to warn the user.
_DATA_CENTER_HOSTNAMES = (
    "googleusercontent",      # Google Cloud Shell
    "google.com", "1e100.net", # Google IPs
    "amazonaws", "aws.amazon", # AWS
    "cloudfront", "azure.com", # Azure / CloudFront
    "digitalocean", "linode",  # Other cloud
    "oracle.com", "oraclecloud",
    "hetzner", "ovh.net",
    "cloudflare",              # often datacenters
)

def detect_environment():
    """Detect IP info and warn if it looks like a data center.

    Returns a dict with: ip, country, city, org, is_datacenter, isp.
    Best-effort: silently returns minimal info on failure.
    """
    info = {
        "ip": "?", "country": "?", "city": "?", "org": "?", "isp": "?",
        "is_datacenter": False, "checked": False,
    }
    # Try ipinfo.io first (free, no key, 50k/month)
    for url, parser in [
        ("https://ipinfo.io/json",
         lambda j: {"ip": j.get("ip", "?"), "country": j.get("country", "?"),
                    "city": j.get("city", "?"), "org": j.get("org", "?"),
                    "isp": j.get("org", "?")}),
        ("https://api.ipify.org?format=json",
         lambda j: {"ip": j.get("ip", "?")}),
    ]:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "ytdown/3.5"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                import json as _json
                data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
                parsed = parser(data)
                info.update(parsed)
                info["checked"] = True
                break
        except Exception:
            continue
    if not info["checked"]:
        return info
    # Heuristic: check if hostname / org contains data-center keywords
    org_lower = (info.get("org", "") + " " + info.get("isp", "")).lower()
    for kw in _DATA_CENTER_HOSTNAMES:
        if kw in org_lower:
            info["is_datacenter"] = True
            break
    return info


def print_environment_diagnostics():
    """Print a clear diagnostic block: IP type, yt-dlp version, cookies.

    Helps the user understand WHY YouTube might be blocking them.
    """
    print("🔍  Environment diagnostics:")
    # yt-dlp version
    try:
        from yt_dlp.version import __version__ as _v
        print(f"   • yt-dlp: {_v}")
    except Exception:
        print("   • yt-dlp: <unknown>")
    # Node.js / Deno (JS challenge solver)
    _node = shutil.which("node")
    _deno = shutil.which("deno")
    if _node:
        print(f"   • Node.js: {_node}")
    elif _deno:
        print(f"   • Deno: {_deno}")
    else:
        print("   • JS runtime: ❌ MISSING — YouTube JS challenges will fail!")
        print("      → Install: https://nodejs.org/ or https://deno.land/")
    # IP info
    env = detect_environment()
    if env["checked"]:
        flag = "🟥 DATA CENTER" if env["is_datacenter"] else "🟩 residential"
        print(f"   • Your IP: {env['ip']} ({env.get('city', '?')}, {env.get('country', '?')}) — {flag}")
        if env["is_datacenter"]:
            print("      ⚠️  YouTube heavily rate-limits data-center IPs (Cloud Shell, AWS, etc.)")
            print("      → Run this script on your PC instead, OR use a residential proxy/VPN.")
        if env.get("org") and env["org"] != "?":
            print(f"      ISP/org: {env['org']}")
    else:
        print("   • IP check: skipped (no network or blocked)")


def test_cookie_validity(cookie_path):
    """Test whether cookies are actually accepted by YouTube.

    Does a lightweight metadata-only request. Returns:
      "ok"           — cookies accepted, video info retrieved
      "format_issue" — cookies accepted but formats unavailable (JS runtime / SABR)
      "auth_failed"  — cookies rejected (Sign in / bot detection)
      "error"        — other error
    """
    if not cookie_path or not os.path.isfile(cookie_path):
        return "error"
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiefile": os.path.expanduser(cookie_path),
            "extractor_args": {"youtube": {"player_client": ["web_safari", "web", "mweb"]}},
        }
        # Skip configs if no JS runtime
        if not shutil.which("node") and not shutil.which("deno"):
            opts["extractor_args"]["youtube"]["player_skip"] = ["configs"]
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                download=False)
            if info and info.get("title"):
                return "ok"
            return "format_issue"
    except Exception as e:
        err = str(e).lower()
        if "sign in" in err or "not a bot" in err:
            return "auth_failed"
        if "format" in err or "no video" in err:
            return "format_issue"
        return "error"


# ═══════════════════════════════════════════════════════════
# 🧅  TOR INTEGRATION (bypasses YouTube bot detection via IP rotation)
# ═══════════════════════════════════════════════════════════

def is_tor_running():
    """Check whether Tor SOCKS5 proxy is reachable on 127.0.0.1:9050."""
    try:
        import socket
        host, port = "127.0.0.1", 9050
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False


def refresh_tor_circuit():
    """Send NEWNYM signal to Tor to rotate IP address.

    Requires Tor to be running with a control port (default 9051) and
    a configured hashed control password (or empty password for default).
    Falls back to 'killall -HUP tor' if control port isn't available.
    """
    # Method 1: use the control port with the stem library (if installed)
    try:
        from stem import Signal
        from stem.control import Controller
        with Controller.from_port(port=CONFIG.get("TOR_CONTROL_PORT", 9051)) as c:
            password = CONFIG.get("TOR_PASSWORD") or None
            c.authenticate(password=password)
            c.signal(Signal.NEWNYM)
            time.sleep(3)  # wait for new circuit
            return True
    except Exception:
        pass

    # Method 2: use torctl CLI (alternative control tool)
    try:
        subprocess.run(["torctl", "newid"], capture_output=True, timeout=5, check=True)
        time.sleep(3)
        return True
    except Exception:
        pass

    # Method 3: HUP signal — simplest, works without control port config
    for cmd in (["killall", "-HUP", "tor"],
                ["pkill", "-HUP", "-f", "tor"],
                ["sudo", "killall", "-HUP", "tor"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, check=True)
            time.sleep(5)
            return True
        except Exception:
            continue
    return False


def try_install_tor():
    """Best-effort Tor installer. Linux only (apt/dnf/yum)."""
    if is_tor_running():
        return True
    is_windows = sys.platform.startswith("win")
    is_macos = sys.platform == "darwin"
    if is_windows:
        return False  # user must install via Tor Browser bundle
    cmds = []
    if is_macos:
        cmds = [["brew", "install", "tor"]]
    else:
        cmds = [
            ["sudo", "apt", "update"],
            ["sudo", "apt", "install", "-y", "tor"],
            ["sudo", "dnf", "install", "-y", "tor"],
            ["sudo", "yum", "install", "-y", "tor"],
        ]
    for cmd in cmds:
        try:
            print(f"   ↪ {' '.join(cmd)}")
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        if shutil.which("tor"):
            return True
    return False


# ═══════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION
# ═══════════════════════════════════════════════════════════

CONFIG = {
    # 📁 Output folder (auto-created if missing)
    "OUTPUT_DIR": "yt_downloads",

    # 🎞️  Default quality: "best" / "2160" / "1440" / "1080" / "720" / "480" / "360" / "audio"
    "DEFAULT_QUALITY": "best",

    # 📦  Default container: "mp4" / "mkv" / "webm" / "mp3" / "m4a"
    "DEFAULT_FORMAT": "mp4",

    # 🔢  Default count: 0 means "download everything"
    "DEFAULT_COUNT": 0,

    # 📝  Max filename length (in characters). Set 0 for "no limit".
    #    200 is generous — covers most YouTube titles. Use 0 only if your
    #    filesystem supports long names.
    "MAX_FILENAME_LENGTH": 200,

    # 🔁  Retry attempts per video (Zero-Skip guarantee)
    "RETRY_ATTEMPTS": 3,
    "RETRY_DELAYS": [5, 10, 15],

    # 🌐  Proxy: leave empty string "" to disable
    # Examples:
    #   "socks5://127.0.0.1:9050"     (Tor SOCKS5)
    #   "http://127.0.0.1:8080"       (HTTP proxy)
    "PROXY": "",

    # 🧅  Tor integration (best for bypassing YouTube bot detection)
    # When USE_TOR = True, the script:
    #   1. Routes all traffic through Tor (socks5h proxy)
    #   2. Refreshes the Tor circuit (rotates IP) between downloads
    #   3. Auto-retries with a new IP on 429 / bot-detection errors
    "USE_TOR":           True,
    "TOR_PROXY":         "socks5h://127.0.0.1:9050",
    "TOR_CONTROL_PORT":  9051,
    "TOR_PASSWORD":      "",     # Set if your torrc has hashed control password

    # 🍪  Cookies for YouTube auth (if "Sign in to confirm" appears)
    #     Either set COOKIE_FILE to a path (e.g. "/tmp/yt-cookies.txt")
    #     OR set COOKIE_BROWSER to "chrome"/"firefox"/"edge"/"brave" to load
    #     from your local browser (must be closed first).
    "COOKIE_FILE": "",
    "COOKIE_BROWSER": "",

    # 🔑  YouTube PO token (advanced, from BG helper)
    "PO_TOKEN": "",

    # 🗣️  Download subtitles / closed-captions
    "DOWNLOAD_SUBS": True,
    # 🗣️  Subtitle languages to try (first available wins; skip 429s gracefully)
    "SUB_LANGS": ["en"],

    # 🖼️  Embed thumbnail into the audio file (mp3 / m4a)
    "EMBED_THUMB": True,

    # 📝  Write video description & metadata to a sidecar .info.json
    "WRITE_INFO_JSON": True,

    # 🗜️  Automatically zip the download folder when everything is done
    "AUTO_ZIP": True,

    # 🚦  Rate-limit (bytes/sec). 0 = unlimited
    "RATE_LIMIT": 0,

    # 🔇  Quiet mode (less log noise on screen)
    "QUIET": False,
}


# Auto-detect / install Tor (after CONFIG so we can read USE_TOR flag)
TOR_AVAILABLE = is_tor_running()
if not TOR_AVAILABLE and CONFIG.get("USE_TOR"):
    print("   ℹ️  Tor not detected on 127.0.0.1:9050 — trying to install/start…")
    if try_install_tor():
        # Try to start tor in background (Linux/macOS)
        if not is_tor_running():
            try:
                subprocess.Popen(["tor"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                time.sleep(5)  # wait for Tor to start
            except Exception:
                pass
        TOR_AVAILABLE = is_tor_running()
        if TOR_AVAILABLE:
            print("   ✅ Tor started successfully")
    print("   Then: yt-dlp will auto-detect it for YouTube extraction")


# ═══════════════════════════════════════════════════════════
# 🛠️  UTILITIES
# ═══════════════════════════════════════════════════════════

BANNER = r"""
   __     __  ____  ___    _   _      _    ___
   \ \   / / |__  || __|  | | | | ___| |_ / _ \
    \ \ / /    / / | _|   | |_| |/ _ \ __| (_) |
     \ V /    / /  | |__  |  _  |  __/ |_ \___/
      \_/    /_/   |____| |_| |_|\___|\__|

   📺 YouTube Video Downloader  ·  v3.5
   🧅  Tor IP Rotation · 🛡️ Bot-Bypass · 🍪 Cookies · 🔑 PO Token · 🔤 Unicode
"""


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def hr(char="─", n=60):
    print(char * n)


def ask(prompt, default=None, choices=None):
    """Friendly input prompt with optional default + choices."""
    suffix = f" [{'/'.join(choices)}]" if choices else ""
    if default is not None:
        suffix += f" (default: {default})"
    suffix += ": "
    while True:
        val = input(prompt + suffix).strip()
        if not val and default is not None:
            return default
        if choices and val not in choices:
            print(f"   ⚠️  Please pick one of: {', '.join(choices)}")
            continue
        return val


def ask_int(prompt, default=0, minimum=0):
    while True:
        val = ask(prompt, default=default)
        try:
            n = int(val)
            if n < minimum:
                print(f"   ⚠️  Must be ≥ {minimum}")
                continue
            return n
        except ValueError:
            print("   ⚠️  Please enter a whole number (0 = all).")


def ask_yn(prompt, default=True):
    val = ask(prompt, default="y" if default else "n", choices=["y", "n", "yes", "no"])
    return val.startswith("y")


def check_cookie_health(cookie_path):
    """Verify a cookie file has the required YouTube auth cookies.

    YouTube bot-detection needs at minimum: LOGIN_INFO, SAPISID,
    __Secure-1PSID, __Secure-3PSID, __Secure-1PSIDTS, __Secure-3PSIDTS.
    Returns a list of missing cookie names (empty list = healthy).
    """
    if not cookie_path or not os.path.isfile(cookie_path):
        return ["<file not found>"]
    required = [
        "LOGIN_INFO",        # proves you're logged in
        "__Secure-1PSID",    # session ID
        "__Secure-3PSID",    # session ID
        "SAPISID",           # auth hash
        "__Secure-1PSIDTS",  # session timestamp
        "__Secure-3PSIDTS",  # session timestamp
    ]
    try:
        with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return [f"<read error: {e}>"]
    # Detect format: Netscape starts with "# Netscape" or has tab-separated
    # rows. JSON starts with "{". Both are valid for yt-dlp, but
    # missing-cookie detection only works for Netscape.
    if content.lstrip().startswith("{"):
        return []  # JSON format — can't easily check, assume OK
    missing = [name for name in required if name not in content]
    return missing


def safe_name(s, limit=None):
    """Sanitize a string into a safe filename, word-boundary truncated.

    Preserves Unicode characters (Bengali, Hindi, emoji, accented letters)
    so the output filename matches the actual YouTube title as closely as
    possible. Only removes:
      - Control characters (0x00-0x1F, 0x7F)
      - Filesystem-unsafe chars: \\ / * ? : " < > |
    """
    if not s:
        return ""
    if limit is None:
        limit = CONFIG.get("MAX_FILENAME_LENGTH", 200) or 0

    # 1. Remove control characters
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    # 2. Remove filesystem-unsafe chars (keep Unicode letters, emoji, accents!)
    s = re.sub(r'[\\/*?:"<>|]', " ", s)
    # 3. Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    if not s:
        return ""

    # 4. Word-boundary truncate to limit (use character count, not bytes)
    if limit and len(s) > limit:
        cut = s[:limit]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        s = cut.strip(" .-_")
    return s


def unique_path(folder, base, ext):
    """Return a non-conflicting path (foo.mp4 → foo_1.mp4 → foo_2.mp4 …)."""
    p = Path(folder) / f"{base}{ext}"
    if not p.exists():
        return p
    i = 1
    while True:
        p = Path(folder) / f"{base}_{i}{ext}"
        if not p.exists():
            return p
        i += 1


def human_bytes(n):
    if not n:
        return "?"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec):
    if not sec or sec == "?":
        return "?"
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


# ═══════════════════════════════════════════════════════════
# 🔍  URL DETECTION
# ═══════════════════════════════════════════════════════════

URL_PATTERNS = {
    "video":  r"(?:https?://)?(?:www\.|m\.)?youtu(?:be\.com/watch\?v=|\.be/)([\w-]{11})",
    "shorts": r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([\w-]{11})",
    "playlist": r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([\w-]+)",
    "channel_videos":  r"(?:https?://)?(?:www\.)?youtube\.com/(?:@[\w.-]+|channel/[\w-]+)/videos",
    "channel_streams": r"(?:https?://)?(?:www\.)?youtube\.com/(?:@[\w.-]+|channel/[\w-]+)/streams",
    "channel_shorts":  r"(?:https?://)?(?:www\.)?youtube\.com/(?:@[\w.-]+|channel/[\w-]+)/shorts",
    # Base channel URL (no /videos, /streams, /shorts) — defaults to /videos
    "channel_base":    r"(?:https?://)?(?:www\.)?youtube\.com/(?:@[\w.-]+|channel/[\w-]+)/?$",
}


def detect_url_kind(url):
    """Return one of: video, shorts, playlist, channel, channel_videos,
    channel_streams, channel_shorts, channel_base, unknown"""
    for kind, pat in URL_PATTERNS.items():
        if re.search(pat, url):
            return kind
    return "unknown"


def normalize_channel_url(url):
    """If the URL is a base channel URL (no /videos /streams /shorts),
    append /videos so yt-dlp enumerates all videos."""
    if re.search(URL_PATTERNS["channel_base"], url):
        url = url.rstrip("/") + "/videos"
    return url


# ═══════════════════════════════════════════════════════════
# 🎛️  YT-DLP FORMAT / OPTION BUILDERS
# ═══════════════════════════════════════════════════════════

def build_format_string(quality, fmt):
    """Return a yt-dlp format selector for the chosen quality + container.

    Uses a multi-step fallback chain to handle:
    - YouTube Shorts (only combined streams available)
    - SABR-only streaming experiment (some formats missing URLs)
    - Region-restricted content
    - Different containers per video
    """
    if quality == "audio":
        if fmt == "mp3":
            return "bestaudio/best"
        if fmt == "m4a":
            return "bestaudio[ext=m4a]/bestaudio/best"
        return "bestaudio/best"

    cap = "" if quality in ("best",) else f"[height<=?{quality}]"

    ext_pref = ""
    if fmt in ("mp4", "mkv", "webm"):
        ext_pref = f"[ext={fmt}]"

    # Build fallback chain:
    # 1. bestvideo (specific container) + bestaudio (specific audio ext)
    # 2. bestvideo + bestaudio (any container — ffmpeg will remux)
    # 3. best (specific container) — combined stream (common for Shorts)
    # 4. best (any container) — absolute fallback
    # This handles Shorts where only combined streams exist, and SABR
    # experiments where separate streams may be missing.
    return (
        f"bestvideo{cap}{ext_pref}+bestaudio{best_audio_ext(fmt)}"
        f"/bestvideo{cap}+bestaudio"
        f"/best{cap}{ext_pref}"
        f"/best"
    )


def best_audio_ext(fmt):
    if fmt == "mp4":
        return "[ext=m4a]"
    if fmt == "webm":
        return "[ext=webm]"
    return ""


def build_ydl_opts(quality, fmt, output_template, write_subs, embed_thumb,
                   write_info_json, proxy, rate_limit, quiet):
    """Return a fresh yt-dlp options dict."""
    opts = {
        "format": build_format_string(quality, fmt),
        "outtmpl": output_template,
        "noplaylist": False,
        # ignoreerrors lets us survive single-subtitle 429s without losing the video
        "ignoreerrors": True,
        "retries": 2,
        "fragment_retries": 2,
        "skip_unavailable_fragments": True,
        "writethumbnail": bool(embed_thumb and quality == "audio"),
        "geo_bypass": True,
        "no_warnings": quiet,
        "quiet": quiet,
        "progress_hooks": [],
    }

    # 🌐  Proxy / Tor configuration (smart):
    # Priority: Cookies > Tor > Manual proxy > Nothing
    #
    # Why cookies beat Tor:
    #   Cookies are issued for a specific IP (your home IP). Tor rotates
    #   IPs constantly, so YouTube sees an IP mismatch and rejects the
    #   session as suspicious. When cookies are present, we trust them
    #   and skip Tor to avoid the mismatch.
    has_cookies = bool(CONFIG.get("COOKIE_FILE")) or bool(CONFIG.get("COOKIE_BROWSER"))
    if has_cookies:
        # Cookies present — skip Tor even if CONFIG says use it.
        if CONFIG.get("USE_TOR") and TOR_AVAILABLE and not quiet:
            print("   🍪 Cookies loaded → skipping Tor to avoid IP mismatch")
        if proxy and not quiet:
            print("   🍪 Cookies loaded → skipping manual proxy too")
    elif CONFIG.get("USE_TOR") and TOR_AVAILABLE:
        opts["proxy"] = CONFIG.get("TOR_PROXY", "socks5h://127.0.0.1:9050")
        if not quiet:
            print(f"   🧅 Using Tor proxy: {opts['proxy']}")
    elif proxy:
        opts["proxy"] = proxy
        if not quiet:
            print(f"   🌐 Using proxy: {proxy}")
    if rate_limit:
        opts["ratelimit"] = rate_limit
    if write_info_json:
        opts["writeinfojson"] = True

    # 🛡️  YouTube bot-detection bypass (4 layers):
    # YouTube started requiring sign-in in 2024+. We try multiple player
    # clients + an alternative YouTube "PO token" mechanism.
    #
    # When cookies are present, yt-dlp automatically skips clients that
    # don't support cookies (ios, android, android_vr, tv_embedded).
    # We put web_safari first because it uses curl_cffi TLS impersonation
    # which bypasses the JS challenge entirely.
    has_cookies_now = bool(CONFIG.get("COOKIE_FILE")) or bool(CONFIG.get("COOKIE_BROWSER"))
    if has_cookies_now:
        # Cookie-compatible clients only
        clients = ["web_safari", "web_creator", "mweb", "web"]
    else:
        # All clients — non-cookie clients may bypass bot detection
        clients = ["web_safari", "ios", "tv_embedded", "android_vr",
                   "android", "web_creator", "mweb", "web"]

    opts["extractor_args"] = {
        "youtube": {
            "player_client": clients,
            "skip": ["translated_subs", "dash"],
            # Allow HLS/DASH livestreams which sometimes bypass the check
            "formats": ["missing_pot"],
        }
    }
    # Skip client config download when JS runtime is missing — this avoids
    # the "n challenge solving failed" warning and the SABR-only issue.
    if not shutil.which("node") and not shutil.which("deno"):
        opts["extractor_args"]["youtube"]["player_skip"] = ["configs"]
        if not quiet:
            print("   ⚡ No JS runtime — skipping client config downloads")

    # 🍪  Cookie support (MOST RELIABLE FIX):
    # 1. Set CONFIG["COOKIE_FILE"] = "/path/to/cookies.txt"  (Netscape format)
    # 2. OR set CONFIG["COOKIE_BROWSER"] = "chrome" / "firefox" / "edge" / "brave"
    if CONFIG.get("COOKIE_FILE"):
        cookie_path = os.path.expanduser(CONFIG["COOKIE_FILE"])
        if os.path.isfile(cookie_path):
            opts["cookiefile"] = cookie_path
            if not quiet:
                print(f"   🍪 Using cookie file: {cookie_path}")
            # Health check: warn if required cookies are missing
            missing = check_cookie_health(cookie_path)
            if missing and not quiet:
                print(f"   ⚠️  Cookie health check: MISSING {len(missing)} required cookie(s):")
                for name in missing[:3]:
                    print(f"      • {name}")
                if len(missing) > 3:
                    print(f"      … and {len(missing) - 3} more")
                print("      → Bot detection may still trigger. Re-export cookies")
                print("         from a browser where you're logged into YouTube.")
        else:
            print(f"   ⚠️  Cookie file not found: {cookie_path}")
            print("      → Re-run and provide a valid path, or")
            print("      → run: mv <file> ~/yt-dlp-cookies.txt")
    elif CONFIG.get("COOKIE_BROWSER"):
        opts["cookiesfrombrowser"] = CONFIG["COOKIE_BROWSER"]
        if not quiet:
            print(f"   🍪 Using browser cookies: {CONFIG['COOKIE_BROWSER']}")
    elif not quiet:
        print("   ⚠️  No cookies configured — YouTube may block downloads.")
        print("      Re-run and answer 'y' to the cookie prompt.")

    # 🔑  YouTube PO token (advanced, from BG helper tool — see yt-dlp wiki)
    if CONFIG.get("PO_TOKEN"):
        opts["extractor_args"]["youtube"]["po_token"] = CONFIG["PO_TOKEN"]

    # For VIDEO downloads: tell yt-dlp to MERGE video+audio into the target
    # container using ffmpeg. Without this, you get a video-only mp4 and a
    # separate m4a side-by-side. merge_output_format forces the merge step.
    if quality != "audio" and fmt in ("mp4", "mkv", "webm"):
        opts["merge_output_format"] = fmt

    if write_subs:
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": CONFIG["SUB_LANGS"],
            "subtitlesformat": "best",
            "embedsubs": True,
        })
    if quality == "audio" and embed_thumb:
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio",
             "preferredcodec": fmt if fmt in ("mp3", "m4a") else "mp3"},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ]
    elif quality == "audio":
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio",
             "preferredcodec": fmt if fmt in ("mp3", "m4a") else "mp3"},
            {"key": "FFmpegMetadata"},
        ]
    elif fmt in ("mp4", "mkv", "webm"):
        # Video: ensure ffmpeg is used for muxing; convertor only when
        # source container != target container (e.g. webm → mp4).
        post = []
        if not FFMPEG_AVAILABLE:
            print("   ⚠️  ffmpeg not found — video and audio will NOT be merged!")
            print("      Install ffmpeg to get a single .mp4 with sound.")
        # Add a metadata pass so the output file has correct title etc.
        post.append({"key": "FFmpegMetadata"})
        # Only convert container when needed
        post.append({"key": "FFmpegVideoConvertor", "preferedformat": fmt})
        opts["postprocessors"] = post

    return opts


# ═══════════════════════════════════════════════════════════
# ⬇️  SINGLE VIDEO DOWNLOADER (with retry)
# ═══════════════════════════════════════════════════════════

def progress_hook(d):
    if CONFIG["QUIET"]:
        return
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        eta = d.get("_eta_str", "").strip()
        print(f"\r   ⬇️  {pct:>6}  {speed:>10}  ETA {eta:<8}", end="", flush=True)
    elif d["status"] == "finished":
        print("\r   ✅ Download finished, post-processing…                    ")


def download_one(url, quality, fmt, out_dir, prefix="", counter=1):
    """Download a single video with retry.

    Returns (ok, filepath, error_msg, real_title).
    The real_title is the actual YouTube title (may differ from a
    placeholder if the caller only had a flat-extracted title).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = None
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err_msg = str(e)
        # If the error is "Sign in to confirm" and we don't have cookies,
        # give the user a clear actionable message
        if "Sign in to confirm" in err_msg or "not a bot" in err_msg:
            if not (CONFIG.get("COOKIE_FILE") or CONFIG.get("COOKIE_BROWSER")):
                err_msg = (
                    "YouTube bot-detection triggered (no cookies configured).\n"
                    "   → Fix: run the script again and answer 'y' to the cookie prompt,\n"
                    "     then provide a cookie file or browser name.\n"
                    "   → Quick fix: on your PC, run:\n"
                    "       yt-dlp --cookies-from-browser chrome --no-download 'https://youtube.com'\n"
                    "     then upload the resulting 'yt-dlp-cookies.txt' to Cloud Shell."
                )
        return False, None, f"info-extract: {err_msg}", ""

    if not info:
        return False, None, "could not fetch video metadata", ""

    title = info.get("title") or "video"
    safe = safe_name(title) or f"video_{info.get('id', int(time.time()))}"
    prefixed = f"{prefix}{counter:03d}_{safe}" if prefix else safe

    outtmpl = str(out_dir / f"{prefixed}.%(ext)s")

    base_opts = build_ydl_opts(
        quality=quality, fmt=fmt, output_template=outtmpl,
        write_subs=CONFIG["DOWNLOAD_SUBS"],
        embed_thumb=CONFIG["EMBED_THUMB"],
        write_info_json=CONFIG["WRITE_INFO_JSON"],
        proxy=CONFIG["PROXY"], rate_limit=CONFIG["RATE_LIMIT"],
        quiet=CONFIG["QUIET"],
    )
    base_opts["progress_hooks"] = [progress_hook]

    last_err = None
    for attempt in range(1, CONFIG["RETRY_ATTEMPTS"] + 1):
        try:
            print(f"\n   ▶️  [{counter}] {title}")
            print(f"   📁 Filename: {prefixed}")
            print(f"   🔁 Attempt {attempt}/{CONFIG['RETRY_ATTEMPTS']}")

            with yt_dlp.YoutubeDL(base_opts) as ydl:
                ydl.download([url])

            produced = None
            for p in out_dir.glob(f"{prefixed}.*"):
                if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mp3",
                                        ".m4a", ".part", ".ytdl", ".info.json"):
                    if not p.name.endswith(".part") and not p.name.endswith(".ytdl"):
                        produced = p
                        break

            if produced and produced.stat().st_size > 1024:
                return True, str(produced), None, title
            for p in out_dir.glob(f"{prefixed}*.part"):
                p.unlink(missing_ok=True)
            last_err = "output file missing or too small (likely error page)"
        except yt_dlp.utils.DownloadError as e:
            last_err = str(e).splitlines()[0][:200]
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        for p in out_dir.glob(f"{prefixed}*"):
            if p.suffix in (".part", ".ytdl") or p.name.endswith(".tmp"):
                p.unlink(missing_ok=True)

        if attempt < CONFIG["RETRY_ATTEMPTS"]:
            wait = CONFIG["RETRY_DELAYS"][attempt - 1]
            print(f"   ⚠️  Failed: {last_err}")

            # 🧅  If using Tor and the error is rate-limit / bot, rotate IP
            if CONFIG.get("USE_TOR") and TOR_AVAILABLE:
                if any(kw in last_err.lower() for kw in
                       ("429", "sign in", "not a bot", "forbidden", "403")):
                    print("   🧅 Refreshing Tor circuit (new IP) for next attempt…")
                    refresh_tor_circuit()

            print(f"   ⏳ Waiting {wait}s before retry…")
            time.sleep(wait)

    return False, None, last_err, title


# ═══════════════════════════════════════════════════════════
# 📋  PLAYLIST ENUMERATION
# ═══════════════════════════════════════════════════════════

def list_videos(url, max_count=0):
    """Return a list of (title, url) tuples for the given URL.

    Handles:
      - Single video / shorts → 1 entry
      - Playlist → all entries
      - Channel / @handle /videos, /streams, /shorts → all entries
      - Base channel URL → all videos (auto-expanded to /videos)
    """
    # Auto-expand base channel URL
    if re.search(URL_PATTERNS["channel_base"], url):
        url = url.rstrip("/") + "/videos"

    # Detect if URL is a channel (any flavor) — these need full extraction
    channel_kinds = ("channel_videos", "channel_streams",
                     "channel_shorts", "channel_base")
    is_channel = any(re.search(URL_PATTERNS[k], url) for k in channel_kinds)

    limit = max_count if max_count else 99999

    if is_channel:
        # For channels: use process_video_entries to recursively follow
        # channel tabs (Shorts, Videos, Streams) and enumerate all videos.
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": limit,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web_safari", "ios", "web"],
                }
            },
        }
    else:
        # For single videos and playlists: use the fast in_playlist mode
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": limit,
        }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"   ⚠️  Failed to list videos: {e}")
        return []

    if not info:
        return []

    # Single video (not a playlist/channel)
    if (info.get("_type") not in ("playlist", "multi_video", "channel", "url")
            and "entries" not in info):
        title = info.get("title") or "video"
        watch_url = info.get("webpage_url") or url
        return [(title, watch_url)]

    entries = info.get("entries") or []
    items = []
    for e in entries:
        if not e:
            continue
        eid = e.get("id")
        etype = e.get("_type", "")

        # Skip channel references (UC + 22 chars = 24 total) — not videos
        if isinstance(eid, str) and eid.startswith("UC") and len(eid) == 24:
            continue

        # For "url" type entries (channel tabs like Shorts/Videos/Streams),
        # recurse to fetch the actual videos
        if etype == "url" and e.get("url") and e.get("url") != url:
            tab_url = e.get("url") or e.get("webpage_url")
            # If eid is 11 chars it's a video id (skip recursion)
            if not (isinstance(eid, str) and len(eid) == 11):
                sub_items = list_videos(tab_url, max_count=max_count)
                items.extend(sub_items)
                if max_count and len(items) >= max_count:
                    break
                continue

        if not eid:
            continue

        # Title: may be missing in flat extraction
        title = e.get("title") or str(eid)
        watch_url = (
            e.get("url")
            or e.get("webpage_url")
            or (f"https://www.youtube.com/watch?v={eid}"
                if isinstance(eid, str) and len(eid) == 11 else None)
        )
        if not watch_url:
            continue
        items.append((title, watch_url))
        if max_count and len(items) >= max_count:
            break
    return items


# ═══════════════════════════════════════════════════════════
# 🗜️  AUTO-ZIP
# ═══════════════════════════════════════════════════════════

def zip_folder(folder, output_zip=None):
    folder = Path(folder)
    if not folder.exists() or not any(folder.iterdir()):
        return None
    if not output_zip:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_zip = folder.parent / f"{folder.name}_{stamp}.zip"
    output_zip = Path(output_zip)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in folder.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(folder.parent))
    return output_zip


# ═══════════════════════════════════════════════════════════
# 🚀  MAIN ENTRY
# ═══════════════════════════════════════════════════════════

def main():
    clear()
    print(BANNER)

    # Show ffmpeg status up-front so users know if merging will work
    if FFMPEG_AVAILABLE:
        ffmpeg_path = has_ffmpeg()
        print(f"   ✅ ffmpeg detected: {ffmpeg_path}")
    else:
        print("   ❌ ffmpeg NOT detected — video+audio merge will fail!")
        print("      Run: sudo apt install ffmpeg   (Linux)")
        print("           brew install ffmpeg       (macOS)")
        print("           install from gyan.dev/ffmpeg/builds  (Windows)")
        if sys.platform.startswith("win"):
            try_install_ffmpeg()

    # 🔧  Auto-install Node.js if missing (YouTube JS challenge solver)
    if not shutil.which("node") and not shutil.which("deno"):
        try_install_nodejs()

    # 🧅  Tor status (smart display)
    if CONFIG.get("USE_TOR"):
        if TOR_AVAILABLE:
            # Will Tor actually be used? It gets skipped if cookies are loaded.
            will_use_tor = not (CONFIG.get("COOKIE_FILE")
                                or CONFIG.get("COOKIE_BROWSER"))
            if will_use_tor:
                print(f"   🧅 Tor proxy: {CONFIG.get('TOR_PROXY')} (IP rotation on errors)")
            else:
                print(f"   🧅 Tor: ready, but cookies take priority (no IP mismatch)")
        else:
            print("   ❌ Tor NOT detected on 127.0.0.1:9050")
            print("      Install:  sudo apt install tor && tor &   (Linux)")
            print("                brew install tor && tor &     (macOS)")
            print("                Tor Browser bundle            (Windows)")
    print()

    # 🔍  Run environment diagnostics — IP type, yt-dlp version, cookies
    print_environment_diagnostics()
    # Cookie test (only if a cookie file is already configured)
    if CONFIG.get("COOKIE_FILE") and os.path.isfile(os.path.expanduser(CONFIG["COOKIE_FILE"])):
        print("   • Testing cookies against YouTube…", end="", flush=True)
        result = test_cookie_validity(CONFIG["COOKIE_FILE"])
        if result == "ok":
            print(" ✅ cookies accepted")
        elif result == "format_issue":
            print(" ⚠️  cookies accepted but formats unavailable")
            print("      → YouTube may be using SABR-only streaming.")
            print("      → Install Node.js for full format support: https://nodejs.org/")
            print("      → Downloads may still work — trying anyway.")
        elif result == "auth_failed":
            print(" ❌ cookies rejected by YouTube")
            print("      → Your cookies may be expired or from a non-logged-in session.")
            print("      → Re-export cookies from a browser where you're logged into YouTube.")
        else:
            print(" ⚠️  test inconclusive (network or yt-dlp error)")
    print()

    url = ""
    while not url:
        url = ask("🔗  Paste YouTube URL (video, shorts, playlist, or channel)")
        if "youtu" in url or detect_url_kind(url) != "unknown":
            break
        print("   ⚠️  That doesn't look like a YouTube URL.")
        url = ""

    kind = detect_url_kind(url)
    print(f"   📌 Detected: {kind}")

    out_dir = ask("📁  Output folder", default=CONFIG["OUTPUT_DIR"])

    quality = ask(
        "🎞️  Quality",
        default=CONFIG["DEFAULT_QUALITY"],
        choices=["best", "2160", "1440", "1080", "720", "480", "360", "audio"],
    )

    fmt = ask(
        "📦  Format (container)",
        default=CONFIG["DEFAULT_FORMAT"],
        choices=["mp4", "mkv", "webm", "mp3", "m4a"],
    )
    if quality == "audio" and fmt not in ("mp3", "m4a"):
        fmt = "mp3"
        print(f"   ℹ️  Audio-only forced container to {fmt}")

    if kind in ("playlist", "channel", "channel_videos", "channel_streams",
                "channel_shorts", "channel_base"):
        count = ask_int("🔢  How many to download?  (0 = all)", default=CONFIG["DEFAULT_COUNT"])
    else:
        count = 1

    # Normalize base channel URL → /videos so yt-dlp enumerates all videos
    if kind == "channel_base":
        new_url = normalize_channel_url(url)
        print(f"   🔗 Base channel URL → expanded to {new_url}")
        url = new_url

    # If it's a shorts URL, show a helpful tip
    if kind == "channel_shorts":
        print(f"   💡 Fetching all shorts from this channel…")
    elif kind in ("channel_videos", "channel_streams"):
        print(f"   💡 Fetching all videos/streams from this channel…")

    # 🍪  Auto-detect cookies: if CONFIG is empty, scan common file paths
    if not CONFIG.get("COOKIE_FILE") and not CONFIG.get("COOKIE_BROWSER"):
        output_dir = out_dir  # where videos will be saved
        candidates = [
            os.path.expanduser("~/yt-dlp-cookies.txt"),
            os.path.expanduser("~/.yt-dlp-cookies.txt"),
            os.path.expanduser("~/cookies.txt"),
            "/tmp/yt-cookies.txt",
            "/tmp/cookies.txt",
            os.path.expanduser("~/youtube-cookies.txt"),
            # Also check inside the video output folder (where users
            # naturally drop cookies)
            os.path.join(output_dir, "yt-dlp-cookies.txt"),
            os.path.join(output_dir, "cookies.txt"),
            os.path.join(output_dir, "youtube-cookies.txt"),
            # Case-insensitive variant (Linux is case-sensitive,
            # but users often type YT_DOWNLOADS vs yt_downloads)
            os.path.join(output_dir.upper(), "yt-dlp-cookies.txt"),
            os.path.join(output_dir.lower(), "yt-dlp-cookies.txt"),
            "yt-dlp-cookies.txt",  # current working dir
            "cookies.txt",
        ]
        for path in candidates:
            if os.path.isfile(path):
                CONFIG["COOKIE_FILE"] = path
                print(f"   🍪 Auto-detected cookie file: {path}")
                break

    subs = ask_yn("🗣️  Download subtitles / CC?", default=CONFIG["DOWNLOAD_SUBS"])
    embed = ask_yn("🖼️  Embed thumbnail into audio files?", default=CONFIG["EMBED_THUMB"])
    info_json = ask_yn("📝  Write .info.json sidecar?", default=CONFIG["WRITE_INFO_JSON"])

    proxy = ask("🌐  Proxy URL (blank = none)", default=CONFIG["PROXY"])
    if proxy:
        CONFIG["PROXY"] = proxy

    # 🍪  Cookie auth — always ask (very common with YouTube in 2024+)
    if not (CONFIG.get("COOKIE_FILE") or CONFIG.get("COOKIE_BROWSER")):
        print("\n   ℹ️  YouTube often requires sign-in (bot detection).")
        print("      Cookies fix this. 3 ways to get them:")
        print("      • On your PC: yt-dlp --cookies-from-browser chrome --no-download 'https://youtube.com'")
        print("        → uploads ~/yt-dlp-cookies.txt to Cloud Shell")
        print("      • Browser extension: 'Get cookies.txt LOCALLY' (Chrome/Firefox)")
        print("      • Or: set CONFIG['COOKIE_BROWSER'] = 'chrome' (if you have a GUI)")
    if ask_yn("🍪  Use cookies for YouTube auth? (fixes 'Sign in' errors)",
              default=bool(CONFIG.get("COOKIE_FILE") or CONFIG.get("COOKIE_BROWSER"))):
        cookie_browser = ask(
            "   Browser to load cookies from [chrome/firefox/edge/brave/safari] (blank = skip): ",
            default=CONFIG.get("COOKIE_BROWSER", ""))
        cookie_file = ask(
            "   Cookie file path (.txt from yt-dlp or browser extension) (blank = skip): ",
            default=CONFIG.get("COOKIE_FILE", ""))
        if cookie_browser:
            CONFIG["COOKIE_BROWSER"] = cookie_browser
        if cookie_file:
            cookie_file = os.path.expanduser(cookie_file)
            if not os.path.isfile(cookie_file):
                # Try resolving relative to common dirs
                for base in [os.getcwd(), out_dir,
                             os.path.expanduser("~"), "/tmp"]:
                    candidate = os.path.join(base, cookie_file)
                    if os.path.isfile(candidate):
                        cookie_file = candidate
                        break
            if os.path.isfile(cookie_file):
                CONFIG["COOKIE_FILE"] = cookie_file
                print(f"   ✅ Cookie file accepted: {cookie_file}")
            else:
                print(f"   ⚠️  Cookie file not found: {cookie_file}")
                print("      Continuing without cookies — bot detection may fail.")
        # Warn loudly if user said 'y' but provided neither
        if not (CONFIG.get("COOKIE_FILE") or CONFIG.get("COOKIE_BROWSER")):
            print()
            print("   ❌ You answered 'y' to use cookies but provided NEITHER")
            print("      a browser name NOR a cookie file path.")
            print("   → Downloads will likely fail with 'Sign in to confirm'.")
            print("   → Re-run and either:")
            print("        a) type 'chrome' / 'firefox' for the browser prompt, OR")
            print("        b) paste the full path to your cookies.txt file.")
            print()
            if not ask_yn("   Continue anyway?", default=True):
                print("Cancelled. Re-run and configure cookies.")
                return 1

    auto_zip = ask_yn("📦  Auto-ZIP the result when done?", default=CONFIG["AUTO_ZIP"])

    CONFIG["DOWNLOAD_SUBS"] = subs
    CONFIG["EMBED_THUMB"] = embed
    CONFIG["WRITE_INFO_JSON"] = info_json

    print("\n⏳  Fetching video list…")
    items = list_videos(url, max_count=count)
    if not items:
        print("❌ No videos found. Check the URL and your network.")
        return 1
    total = len(items)
    print(f"✅  Found {total} video(s)")

    # Show a preview of the first few video titles
    if total > 1:
        preview = items[:5]
        print(f"\n   📃 First {len(preview)} of {total}:")
        for t, u in preview:
            short_t = t if len(t) <= 70 else t[:67] + "..."
            print(f"      • {short_t}")
        if total > 5:
            print(f"      … and {total - 5} more")

    # 🧪  Single-video test: if cookies are configured, do a quick
    # metadata-only check on the first video BEFORE committing to
    # 286 downloads. This catches bad cookies early.
    if CONFIG.get("COOKIE_FILE") or CONFIG.get("COOKIE_BROWSER"):
        if total > 1 and ask_yn(
                f"🧪  Run a 5-second cookie/auth test on the first video? "
                f"(recommended, saves time if cookies are bad)",
                default=True):
            test_url = items[0][1]
            print(f"   🔬 Testing: {test_url}")
            try:
                test_opts = {
                    "quiet": True, "no_warnings": True, "skip_download": True,
                }
                if CONFIG.get("COOKIE_FILE"):
                    test_opts["cookiefile"] = os.path.expanduser(CONFIG["COOKIE_FILE"])
                if CONFIG.get("COOKIE_BROWSER"):
                    test_opts["cookiesfrombrowser"] = CONFIG["COOKIE_BROWSER"]
                with yt_dlp.YoutubeDL(test_opts) as ydl:
                    info = ydl.extract_info(test_url, download=False)
                if info and info.get("title"):
                    print(f"   ✅ Test passed! Got: '{info.get('title')}'")
                    print("   → Cookies are valid. Proceeding with bulk download.")
                else:
                    print("   ⚠️  Test returned no info — cookies may be invalid.")
                    if not ask_yn("   Continue with bulk download anyway?", default=False):
                        print("Cancelled.")
                        return 1
            except Exception as e:
                err = str(e).lower()
                if "sign in" in err or "not a bot" in err:
                    print("   ❌ Test FAILED: 'Sign in to confirm' — cookies rejected.")
                    print("      → Re-export cookies from a logged-in YouTube session.")
                    print("      → Or run on your PC (residential IP).")
                    if not ask_yn("   Continue with bulk download anyway?", default=False):
                        print("Cancelled. Fix cookies and try again.")
                        return 1
                else:
                    print(f"   ⚠️  Test error: {e}")
                    print("   → Continuing with bulk download (may still work).")
            print()

    if not ask_yn(f"🚀  Start downloading {total} video(s)?", default=True):
        print("Cancelled.")
        return 0

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    hr("═")
    started = time.time()
    successes = 0
    failures = []

    for i, (title, vurl) in enumerate(items, 1):
        hr()
        # If the list_videos title is just a video id (random chars), don't show it
        display_title = title
        if re.fullmatch(r"[\w-]{11}", title or ""):
            display_title = "(fetching title…)"
        print(f"📺  [{i}/{total}]  {display_title}")
        print(f"   🌐 {vurl}")
        ok, fpath, err, real_title = download_one(
            url=vurl, quality=quality, fmt=fmt,
            out_dir=out_dir_path, prefix="", counter=i,
        )
        # Use the real title (fetched during download) for the final report
        if real_title:
            title = real_title
        if ok:
            successes += 1
            print(f"   ✅ Saved → {fpath}")
        else:
            failures.append((title, vurl, err))
            print(f"   ❌ FAILED: {err}")

    elapsed = int(time.time() - started)
    hr("═")
    print(f"🏁  Done in {human_time(elapsed)}")
    print(f"    ✅  Success : {successes}/{total}")
    if failures:
        print(f"    ❌  Failed  : {len(failures)}")
        for title, vurl, err in failures:
            print(f"        • {title}  ({vurl})  →  {err}")

    if auto_zip and successes:
        zip_path = zip_folder(out_dir_path)
        if zip_path:
            size = zip_path.stat().st_size
            print(f"📦  Zipped → {zip_path}  ({human_bytes(size)})")

    print("\n👋  Bye!\n")
    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⛔  Interrupted by user.")
        sys.exit(130)
