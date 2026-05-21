import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

AUTH_TOKEN = os.environ.get("YTDLP_WORKER_TOKEN")


def check_auth():
    if not AUTH_TOKEN:
        return
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or header.split(" ", 1)[1] != AUTH_TOKEN:
        from flask import abort
        abort(401, description="Unauthorized")


@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "ytdlp-worker"})


@app.route("/info", methods=["POST"])
def info():
    check_auth()
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formats = []
    for f in info.get("formats", []) or []:
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
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
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

    # Pick a smart selector based on whether the chosen format has video/audio.
    if has_video and has_audio:
        fmt = fmt_id
    elif has_video and not has_audio:
        # Video-only: merge with best audio, fall back to best progressive MP4.
        fmt = f"{fmt_id}+bestaudio/best[ext=mp4]/best"
    elif has_audio and not has_video:
        fmt = f"{fmt_id}/bestaudio/best"
    else:
        fmt = "best[ext=mp4]/best"

    def extract(selector):
        opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "format": selector,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = extract(fmt)
    except Exception as e:
        msg = str(e)
        # Retry once with a safe progressive fallback so the user gets *something*.
        if "Requested format is not available" in msg:
            try:
                info = extract("best[ext=mp4]/best")
            except Exception as e2:
                return jsonify({"error": str(e2)}), 500
        else:
            return jsonify({"error": msg}), 500

    direct = info.get("url")
    if not direct and info.get("requested_formats"):
        # Merged stream — browser can't merge DASH, but progressive 'best'
        # usually returns a single playable URL here.
        direct = info["requested_formats"][0].get("url")
    if not direct:
        return jsonify({
            "error": "No direct URL available; this format needs server-side merging."
        }), 422

    safe = "".join(
        c for c in (info.get("title") or "video") if c.isalnum() or c in " -_"
    ).strip() or "video"
    return jsonify({
        "url": direct,
        "filename": f"{safe}.{info.get('ext') or 'mp4'}",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
