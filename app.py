"""
YouTube downloader worker (Flask + yt-dlp) — Render.
"""

import os
import re
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
if not os.path.exists(COOKIE_FILE):
    print(f"[warn] cookies.txt not found at {COOKIE_FILE}")
    COOKIE_FILE = None

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CLIENT_FALLBACKS = [None, ["web"], ["ios"], ["web_safari"], ["mweb"], ["tv"]]


def base_opts(extra=None, player_clients=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "http_headers": {"User-Agent": UA},
    }
    if player_clients:
        opts["extractor_args"] = {"youtube": {"player_client": player_clients}}
    if COOKIE_FILE:
        opts["cookiefile"] = COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts


def is_bot_block(msg):
    m = msg.lower()
    return "sign in to confirm" in m or "--cookies" in m or "use --cookies" in m


def is_format_unavailable(msg):
    return "format is not available" in msg.lower()


@app.get("/")
def health():
    return jsonify({
        "ok": True,
        "cookies_loaded": COOKIE_FILE is not None,
        "yt_dlp": yt_dlp.version.__version__,
    })


@app.post("/info")
def info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400

    last_err = None
    info_obj = None
    for clients in CLIENT_FALLBACKS:
        try:
            with yt_dlp.YoutubeDL(base_opts(player_clients=clients)) as ydl:
                info_obj = ydl.extract_info(url, download=False)
            break
        except Exception as e:
            msg = str(e)
            if is_bot_block(msg):
                return jsonify({"error": "YouTube is blocking the request. Cookies are missing or expired."}), 401
            last_err = msg
            if not is_format_unavailable(msg):
                return jsonify({"error": msg}), 500

    if info_obj is None:
        return jsonify({"error": last_err or "no client could extract this video"}), 500

    formats = []
    for f in info_obj.get("formats", []) or []:
        if not f.get("format_id"):
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
        "title": info_obj.get("title"),
        "thumbnail": info_obj.get("thumbnail"),
        "duration": info_obj.get("duration"),
        "uploader": info_obj.get("uploader"),
        "channel": info_obj.get("channel"),
        "formats": formats,
    })


def extract_with_selector(url, selector, player_clients=None):
    with yt_dlp.YoutubeDL(base_opts({"format": selector}, player_clients=player_clients)) as ydl:
        return ydl.extract_info(url, download=False)


def pick_url_and_name(info_obj):
    url = info_obj.get("url")
    if not url and info_obj.get("requested_formats"):
        url = info_obj["requested_formats"][0].get("url")
    filename = info_obj.get("title")
    ext = info_obj.get("ext") or "mp4"
    if filename:
        filename = re.sub(r"[\\/:*?\"<>|]+", "_", filename) + f".{ext}"
    return url, filename


@app.post("/download-url")
def download_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "").strip()
    has_video = bool(data.get("hasVideo", True))
    has_audio = bool(data.get("hasAudio", True))
    if not url or not fmt:
        return jsonify({"error": "missing url or format"}), 400

    selectors = []
    if has_video and has_audio:
        selectors += [fmt, f"{fmt}+bestaudio/best[ext=mp4]/best", "best[ext=mp4]/best"]
    elif has_video and not has_audio:
        selectors += [f"{fmt}+bestaudio/best[ext=mp4]/best", "best[ext=mp4]/best"]
    else:
        selectors += [fmt, "bestaudio/best"]

    last_err = None
    for sel in selectors:
        for clients in CLIENT_FALLBACKS:
            try:
                info_obj = extract_with_selector(url, sel, player_clients=clients)
                picked, name = pick_url_and_name(info_obj)
                if picked:
                    return jsonify({"url": picked, "filename": name})
                last_err = "no stream url returned"
            except Exception as e:
                msg = str(e)
                if is_bot_block(msg):
                    return jsonify({"error": "YouTube is blocking the request. Cookies are missing or expired."}), 401
                last_err = msg
                if not is_format_unavailable(msg):
                    break

    return jsonify({"error": last_err or "no usable format found"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
