import os
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

AUTH_TOKEN = os.environ.get("YTDLP_WORKER_TOKEN")  # set on Render

def check_auth():
    if not AUTH_TOKEN:
        return  # auth disabled
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {AUTH_TOKEN}":
        abort(401, description="Invalid token")

@app.route("/", methods=["GET"])
def home():
    return "YT API Running!"

@app.route("/info", methods=["POST"])
def info():
    check_auth()
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formats = []
    for f in info.get("formats", []):
        if not f.get("url"):
            continue
        has_v = f.get("vcodec") and f["vcodec"] != "none"
        has_a = f.get("acodec") and f["acodec"] != "none"
        if not (has_v or has_a):
            continue
        if f.get("height"):
            quality = f"{f['height']}p"
        elif f.get("abr"):
            quality = f"{int(f['abr'])}kbps"
        else:
            quality = f.get("format_note") or "—"
        suffix = " (video only)" if has_v and not has_a else " (audio only)" if has_a and not has_v else ""
        formats.append({
            "id": str(f["format_id"]),
            "label": f"{quality} {(f.get('ext') or '').upper()}{suffix}".strip(),
            "ext": f.get("ext") or "mp4",
            "quality": quality,
            "hasVideo": bool(has_v),
            "hasAudio": bool(has_a),
            "size": f.get("filesize") or f.get("filesize_approx"),
        })

    return jsonify({
        "title": info.get("title") or "Untitled",
        "thumbnail": info.get("thumbnail") or "",
        "duration": int(info.get("duration") or 0),
        "author": info.get("uploader") or info.get("channel"),
        "formats": formats,
    })

@app.route("/download-url", methods=["POST"])
def download_url():
    check_auth()
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    fmt = data.get("format")
    if not url or not fmt:
        return jsonify({"error": "Missing 'url' or 'format'"}), 400

    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True, "format": fmt}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    direct = info.get("url")
    if not direct and info.get("requested_formats"):
        direct = info["requested_formats"][0].get("url")
    if not direct:
        return jsonify({"error": "No direct URL for that format"}), 422

    safe_title = "".join(c for c in (info.get("title") or "video") if c.isalnum() or c in " -_").strip()
    return jsonify({"url": direct, "filename": f"{safe_title}.{info.get('ext') or 'mp4'}"})
