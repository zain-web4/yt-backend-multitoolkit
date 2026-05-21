import os
import yt_dlp
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

WORKER_TOKEN = os.environ.get("YTDLP_WORKER_TOKEN")
PORT = int(os.environ.get("PORT", "8000"))

# Resolve cookies.txt next to this script and log status at boot
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
if os.path.exists(COOKIE_FILE):
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        if "Netscape HTTP Cookie File" not in first:
            print(f"[warn] cookies.txt found but first line is not Netscape header: {first!r}")
        else:
            print(f"[ok] cookies.txt loaded from {COOKIE_FILE}")
    except Exception as e:
        print(f"[warn] could not read cookies.txt: {e}")
else:
    print(f"[warn] cookies.txt NOT found at {COOKIE_FILE} — YouTube will likely block requests")
    COOKIE_FILE = None

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def check_auth():
    if not WORKER_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {WORKER_TOKEN}":
        abort(401, description="Unauthorized")


def base_opts(extra=None):
    opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
        "http_headers": {"User-Agent": UA},
    }
    if COOKIE_FILE:
        opts["cookiefile"] = COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts


def is_bot_block(msg: str) -> bool:
    m = msg.lower()
    return (
        "sign in to confirm" in m
        or "confirm you" in m
        or "use --cookies" in m
        or "cookies are no longer valid" in m
    )


@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True, "cookies_loaded": bool(COOKIE_FILE)})


@app.route("/info", methods=["POST"])
def info():
    check_auth()
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            raw = ydl.extract_info(url, download=False)
    except Exception as e:
        msg = str(e)
        if is_bot_block(msg):
            return jsonify({"error": "YouTube blocked the request. cookies.txt on the server is missing, invalid, or expired. Re-export from a logged-in browser in Netscape format and redeploy."}), 401
        return jsonify({"error": msg}), 500

    formats = []
    for f in raw.get("formats") or []:
        if not f:
            continue
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": f.get("height"),
            "width": f.get("width"),
            "fps": f.get("fps"),
            "abr": f.get("abr"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "format_note": f.get("format_note"),
            "filesize": f.get("filesize"),
            "filesize_approx": f.get("filesize_approx"),
            "url": f.get("url"),
        })

    return jsonify({
        "title": raw.get("title"),
        "thumbnail": raw.get("thumbnail"),
        "duration": raw.get("duration"),
        "uploader": raw.get("uploader"),
        "channel": raw.get("channel"),
        "formats": formats,
    })


@app.route("/download-url", methods=["POST"])
def download_url():
    check_auth()
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    fmt_id = data.get("format")
    has_video = bool(data.get("hasVideo", True))
    has_audio = bool(data.get("hasAudio", True))
    if not url or not fmt_id:
        return jsonify({"error": "Missing 'url' or 'format'"}), 400

    if has_video and has_audio:
        fmt = fmt_id
    elif has_video and not has_audio:
        fmt = f"{fmt_id}+bestaudio/best[ext=mp4]/best"
    elif has_audio and not has_video:
        fmt = f"{fmt_id}/bestaudio/best"
    else:
        fmt = "best[ext=mp4]/best"

    def extract(selector):
        with yt_dlp.YoutubeDL(base_opts({"format": selector})) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info_ = extract(fmt)
    except Exception as e:
        msg = str(e)
        if is_bot_block(msg):
            return jsonify({"error": "YouTube blocked the request. cookies.txt on the server is missing, invalid, or expired. Re-export from a logged-in browser in Netscape format and redeploy."}), 401
        if "Requested format is not available" in msg:
            try:
                info_ = extract("best[ext=mp4]/best")
            except Exception as e2:
                return jsonify({"error": str(e2)}), 500
        else:
            return jsonify({"error": msg}), 500

    direct = info_.get("url")
    if not direct and info_.get("requested_formats"):
        direct = info_["requested_formats"][0].get("url")
    if not direct:
        return jsonify({"error": "No direct URL available; this format needs server-side merging."}), 422

    safe = "".join(c for c in (info_.get("title") or "video") if c.isalnum() or c in " -_").strip()
    return jsonify({"url": direct, "filename": f"{safe}.{info_.get('ext') or 'mp4'}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
