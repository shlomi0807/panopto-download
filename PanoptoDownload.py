#!/usr/bin/env python3
"""
Panopto Lecture Downloader (highest available quality)
========================================================

What this does
---------------
You paste the URL of a Panopto "Viewer.aspx" lecture page that YOU are
already authorized to view with your own university account. The script:

  1. Opens a real Chrome/Chromium window (via Playwright) using a persistent
     profile, so you only have to log in once.
  2. Waits for you to log in (if needed) and press Play on the lecture.
  3. Watches the network traffic for the HLS master playlist (master.m3u8)
     or, for Zoom-uploaded recordings, a direct CloudFront MP4 URL.
  4. Automatically picks the highest-resolution HLS variant (e.g. 1080p).
  5. Downloads every byte-range segment of the underlying fragmented.mp4
     (this is required because Panopto serves one big MP4 file sliced via
     HTTP Range requests, not separate .ts segment files).
  6. Remuxes everything into a clean, seekable MP4 with ffmpeg.
  7. Saves the result to your Desktop.

This does NOT bypass DRM or any access control. It simply automates
grabbing the exact same authenticated stream URLs your browser already
requests when you watch the lecture, and reassembles them into one file
for offline viewing.

Requirements (בשימוש הראשון: חובה להתקין את כל הספריות. לאחר ההורדה, סגור ופתח מחדש את החלון)
------------
    pip install playwright requests
    playwright install chromium
    winget install Gyan.FFmpeg

Usage
-----
    הרץ את הסקריפט בכל דרך שתבחר

    לאחר מכן הדבק את הכתובת של השיעור שאתה רוצה להוריד

    אחר כך הדבק את המיקום בו תרצה לשמור את ההורדות (לחץ ENTER כדי לשמור בשולחן עבודה )

    בחלון שייפתח בחר moodle 4.5

    התחבר עם שם משתמש וסיסמה של המודל

    ההורדה תתחיל אוטומטית

"""


import re
import sys
import time
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed.")
    print("Run:  pip install playwright requests")
    print("Then: playwright install chromium")
    sys.exit(1)


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

NETWORK_WAIT_SECONDS = 300   # max total time to wait for any stream to appear
QUIET_PERIOD_SECONDS = 4     # stop collecting once no new stream URL for this long
MAX_COLLECT_SECONDS = 40     # but never collect for longer than this after first hit

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# If ffmpeg is not found automatically (common in PyCharm, whose
# terminal/run-configuration PATH can be stale), set the full path to
# ffmpeg.exe here manually, e.g.:
#   FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
# Leave as None to auto-detect via PATH.
FFMPEG_PATH = None


# ----------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------

def get_desktop_dir() -> Path:
    return Path.home() / "Desktop"


def get_profile_dir() -> Path:
    if sys.platform == "win32":
        import os
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        d = base / "PanoptoDownloader" / "ChromeProfile"
    else:
        d = Path.home() / ".panopto_downloader_profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_temp_dir() -> Path:
    d = Path.home() / ".panopto_downloader_temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_ffmpeg() -> str:
    if FFMPEG_PATH:
        if Path(FFMPEG_PATH).exists():
            return FFMPEG_PATH
        print(f"FFMPEG_PATH is set to '{FFMPEG_PATH}' but that file does not exist.")
        sys.exit(1)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg was not found on PATH.")
        print()
        print("Install it (e.g. `winget install ffmpeg` on Windows), open a")
        print("fresh terminal, and try again. Or set FFMPEG_PATH near the")
        print("top of this script to the full path of ffmpeg.exe.")
        sys.exit(1)
    return ffmpeg


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:150] if name else "lecture"


def unique_path(path: Path) -> Path:
    """Return `path`, or `path (1)`, `path (2)`, ... if it already exists."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ----------------------------------------------------------------------
# Step 1: Open the browser, capture ALL stream URLs
# ----------------------------------------------------------------------

def capture_streams(page_url: str):
    """Open Chromium, navigate to the Panopto page, and capture every
    HLS master playlist / variant playlist and direct CloudFront MP4
    request seen, until things go quiet for a while."""

    profile_dir = get_profile_dir()
    captured = {"m3u8": [], "mp4": []}

    with sync_playwright() as p:
        print("\nOpening Chrome (Chromium)...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1400, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_request(request):
            url = request.url
            if ".m3u8" in url:
                if url not in captured["m3u8"]:
                    captured["m3u8"].append(url)
            elif ".mp4" in url and "cloudfront" in url.lower():
                if url not in captured["mp4"]:
                    captured["mp4"].append(url)

        page.on("request", on_request)

        print("Navigating to the Panopto page...")
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"Warning: page.goto reported: {e}")

        print()
        print("If needed, log in to your university account now.")
        print("Then press PLAY on the lecture in the opened window.")
        print("If the lecture has multiple video panels (e.g. camera +")
        print("screen share), Panopto usually starts both automatically.")
        print(f"Waiting up to {NETWORK_WAIT_SECONDS} seconds for stream(s)...")
        print()

        deadline = time.time() + NETWORK_WAIT_SECONDS
        first_seen_at = None
        quiet_since = None
        last_total = 0

        while time.time() < deadline:
            total = len(captured["m3u8"]) + len(captured["mp4"])

            if total > 0:
                if first_seen_at is None:
                    first_seen_at = time.time()
                    quiet_since = time.time()
                    last_total = total
                    print(f"  detected stream #{total}...")
                elif total != last_total:
                    print(f"  detected stream #{total}...")
                    last_total = total
                    quiet_since = time.time()

                now = time.time()
                if now - quiet_since >= QUIET_PERIOD_SECONDS:
                    break
                if now - first_seen_at >= MAX_COLLECT_SECONDS:
                    break

            page.wait_for_timeout(500)

        try:
            title = page.title()
        except Exception:
            title = None

        cookies = context.cookies()
        context.close()

    return captured, cookies, title


def make_session(cookies, referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Referer": referer})
    for c in cookies:
        try:
            session.cookies.set(
                c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/")
            )
        except Exception:
            pass
    return session


# ----------------------------------------------------------------------
# Grouping: multiple streams -> one group per underlying video
# ----------------------------------------------------------------------

def stream_group_key(url: str) -> str:
    """URLs belonging to the same underlying video (different quality
    variants of the same stream, or the raw fragmented.mp4 requests made
    by the HLS player itself) share the same folder - Panopto/CloudFront
    names it '<id>.hls' or '<id>.screen.hls' (note: a DOT before "hls",
    not a slash). URLs from a different video stream (e.g. screen-share
    vs camera) live under a different such folder."""
    parts = urlparse(url).path.split("/")
    for i, part in enumerate(parts):
        if part == "hls" or part.endswith(".hls"):
            return "/".join(parts[: i + 1])
    # Fallback: no recognizable "*.hls" folder - group by parent-of-parent
    # (drops the quality-id and filename segments) so at least same-folder
    # variants collapse together.
    if len(parts) > 2:
        return "/".join(parts[:-2])
    return urlparse(url).path


def group_urls(urls):
    groups = {}
    for url in urls:
        key = stream_group_key(url)
        groups.setdefault(key, []).append(url)
    return groups


def resolve_master_url(urls, session: requests.Session) -> str:
    """Given all captured m3u8 urls for one stream, return a master
    playlist URL to work with - either one that was actually captured,
    or a best-effort derived one, or as a last resort just a captured
    variant playlist (still works, just skips auto quality selection)."""

    masters = [u for u in urls if "master.m3u8" in u.lower()]
    if masters:
        return masters[0]

    sample = urls[0]
    parsed = urlparse(sample)
    parts = parsed.path.split("/")
    hls_idx = None
    for i, part in enumerate(parts):
        if part == "hls" or part.endswith(".hls"):
            hls_idx = i
            break

    if hls_idx is not None:
        candidate_path = "/".join(parts[: hls_idx + 1]) + "/master.m3u8"
        candidate_url = parsed._replace(path=candidate_path).geturl()
        try:
            r = session.get(candidate_url, timeout=15)
            if r.status_code < 400 and "#EXTM3U" in r.text:
                return candidate_url
        except Exception:
            pass

    return sample


# ----------------------------------------------------------------------
# Step 2: Pick the best HLS variant from the master playlist
# ----------------------------------------------------------------------

def pick_best_variant(master_url: str, session: requests.Session):
    resp = session.get(master_url, timeout=30)
    resp.raise_for_status()
    text = resp.text

    if "#EXT-X-STREAM-INF" not in text:
        # Already a media (variant) playlist, not a master.
        return master_url, text

    lines = text.splitlines()
    best_uri = None
    best_height = -1
    best_bandwidth = -1

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue

        height = 0
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        if m:
            height = int(m.group(1))

        bandwidth = 0
        m = re.search(r"BANDWIDTH=(\d+)", line)
        if m:
            bandwidth = int(m.group(1))

        if i + 1 >= len(lines):
            continue
        uri_line = lines[i + 1].strip()
        if not uri_line or uri_line.startswith("#"):
            continue

        if (height, bandwidth) > (best_height, best_bandwidth):
            best_height, best_bandwidth, best_uri = height, bandwidth, uri_line

    if not best_uri:
        raise RuntimeError("No variant streams found inside the master playlist.")

    variant_url = urljoin(master_url, best_uri)

    master_parts = urlparse(master_url)
    variant_parts = urlparse(variant_url)
    if master_parts.query and not variant_parts.query:
        variant_url = variant_url + "?" + master_parts.query

    if best_height:
        print(f"    selected variant: {best_height}p")

    resp2 = session.get(variant_url, timeout=30)
    resp2.raise_for_status()
    return variant_url, resp2.text


# ----------------------------------------------------------------------
# Step 3: Parse the media playlist (init segment + byte-range segments)
# ----------------------------------------------------------------------

def parse_media_playlist(variant_url: str, text: str):
    init_uri = None
    init_offset = 0
    init_length = 0
    segments = []  # (uri, offset_or_None, length_or_None)
    pending_range = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                init_uri = urljoin(variant_url, m.group(1))
            m = re.search(r'BYTERANGE="(\d+)@(\d+)"', line)
            if m:
                init_length = int(m.group(1))
                init_offset = int(m.group(2))
            continue

        if line.startswith("#EXT-X-BYTERANGE:"):
            m = re.search(r"(\d+)@(\d+)", line)
            if m:
                pending_range = (int(m.group(2)), int(m.group(1)))  # (offset, length)
            continue

        if line and not line.startswith("#"):
            seg_uri = urljoin(variant_url, line)
            if pending_range:
                offset, length = pending_range
            else:
                offset, length = None, None
            segments.append((seg_uri, offset, length))
            pending_range = None

    if not segments:
        raise RuntimeError("No media segments found in the playlist.")

    return init_uri, init_offset, init_length, segments


# ----------------------------------------------------------------------
# Step 4: Download helpers
# ----------------------------------------------------------------------

def download_piece(session, url, offset, length, out_fh, retries=4):
    headers = {}
    if offset is not None and length is not None:
        headers["Range"] = f"bytes={offset}-{offset + length - 1}"

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, headers=headers, stream=True, timeout=60) as r:
                if headers and r.status_code not in (200, 206):
                    raise RuntimeError(f"Unexpected HTTP status {r.status_code}")
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out_fh.write(chunk)
            return
        except Exception as e:
            last_error = e
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Failed to download {url}: {last_error}")


def print_progress(done, total, prefix="    downloading"):
    pct = int((done / total) * 100) if total else 0
    bar_len = 30
    filled = int(bar_len * done / total) if total else 0
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"\r{prefix} [{bar}] {pct}%  ({done}/{total})", end="", flush=True)
    if done == total:
        print()


def remux_to_final(ffmpeg: str, temp_file: Path, final_file: Path):
    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", str(temp_file),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c", "copy",
            "-movflags", "+faststart",
            str(final_file),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print("\nffmpeg failed:")
        print(result.stderr[-3000:])
        print(f"Raw downloaded file is still available at:\n  {temp_file}")
        return False
    return True


# ----------------------------------------------------------------------
# Per-stream download routines
# ----------------------------------------------------------------------

def download_hls_stream(urls, session, ffmpeg, temp_dir, final_file: Path) -> bool:
    master_url = resolve_master_url(urls, session)
    print(f"    playlist: {master_url.split('?')[0]}")

    variant_url, variant_text = pick_best_variant(master_url, session)
    init_uri, init_offset, init_length, segments = parse_media_playlist(variant_url, variant_text)

    total_pieces = (1 if init_uri else 0) + len(segments)
    done_pieces = 0
    temp_file = temp_dir / (final_file.stem + "_raw.mp4")
    if temp_file.exists():
        temp_file.unlink()

    print(f"    segments: {len(segments)}")

    with open(temp_file, "wb") as out_fh:
        if init_uri:
            download_piece(session, init_uri, init_offset, init_length, out_fh)
            done_pieces += 1
            print_progress(done_pieces, total_pieces)

        for seg_uri, offset, length in segments:
            download_piece(session, seg_uri, offset, length, out_fh)
            done_pieces += 1
            print_progress(done_pieces, total_pieces)

    ok = remux_to_final(ffmpeg, temp_file, final_file)
    if ok and temp_file.exists():
        temp_file.unlink()
    return ok


def download_direct_mp4_stream(urls, session, ffmpeg, temp_dir, final_file: Path) -> bool:
    mp4_url = urls[0]
    print(f"    direct MP4: {mp4_url.split('?')[0]}")

    temp_file = temp_dir / (final_file.stem + "_raw.mp4")
    if temp_file.exists():
        temp_file.unlink()

    with open(temp_file, "wb") as out_fh:
        download_piece(session, mp4_url, None, None, out_fh)

    ok = remux_to_final(ffmpeg, temp_file, final_file)
    if ok and temp_file.exists():
        temp_file.unlink()
    return ok


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    print("=" * 50)
    print("        PANOPTO LECTURE DOWNLOADER")
    print("=" * 50)

    page_url = input("\nPaste Panopto lecture URL: ").strip()
    if not page_url.lower().startswith("http"):
        print("That doesn't look like a valid URL.")
        sys.exit(1)

    ffmpeg = find_ffmpeg()

    default_dir = get_desktop_dir()
    dest_input = input(
        f"\nWhere should the recordings be saved? (Enter = {default_dir}): "
    ).strip().strip('"')

    if dest_input:
        output_dir = Path(dest_input).expanduser()
    else:
        output_dir = default_dir

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Could not use that folder ({e}). Falling back to Desktop.")
        output_dir = default_dir
        output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = get_temp_dir()

    captured, cookies, page_title = capture_streams(page_url)

    if not captured["m3u8"] and not captured["mp4"]:
        print("\nNo video stream was detected.")
        print("Make sure the lecture actually started playing, then try again.")
        sys.exit(1)

    session = make_session(cookies, referer=page_url)

    m3u8_groups = group_urls(captured["m3u8"])
    mp4_groups_all = group_urls(captured["mp4"])
    # Drop mp4 "streams" that are actually just the HLS player's own
    # byte-range requests against fragmented.mp4 for a stream we're
    # already downloading via its m3u8 - those are the exact same file,
    # not a separate video.
    mp4_groups = {k: v for k, v in mp4_groups_all.items() if k not in m3u8_groups}
    total_streams = len(m3u8_groups) + len(mp4_groups)

    print(f"\nFound {total_streams} video stream(s) for this lecture.")

    base_name = sanitize_filename(page_title) if page_title else "lecture"
    folder = unique_path(output_dir / base_name)
    folder.mkdir(parents=True, exist_ok=True)

    results = []
    stream_index = 0
    failures = 0

    for _key, urls in m3u8_groups.items():
        stream_index += 1
        label = f"Video {stream_index}" if total_streams > 1 else base_name
        final_file = unique_path(folder / f"{sanitize_filename(label)}.mp4")

        print(f"\n=== Stream {stream_index}/{total_streams} (HLS) -> {final_file.name} ===")
        try:
            ok = download_hls_stream(urls, session, ffmpeg, temp_dir, final_file)
        except Exception as e:
            print(f"    FAILED: {e}")
            ok = False

        if ok:
            results.append(final_file)
        else:
            failures += 1

    for _key, urls in mp4_groups.items():
        stream_index += 1
        label = f"Video {stream_index}" if total_streams > 1 else base_name
        final_file = unique_path(folder / f"{sanitize_filename(label)}.mp4")

        print(f"\n=== Stream {stream_index}/{total_streams} (direct MP4) -> {final_file.name} ===")
        try:
            ok = download_direct_mp4_stream(urls, session, ffmpeg, temp_dir, final_file)
        except Exception as e:
            print(f"    FAILED: {e}")
            ok = False

        if ok:
            results.append(final_file)
        else:
            failures += 1

    print("\n" + "=" * 50)
    if results:
        print("            DOWNLOAD COMPLETE")
        print("=" * 50)
        print(f"\nSaved {len(results)} file(s) to: {folder}")
        for f in results:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  - {f.name}  ({size_mb:.2f} MB)")
    if failures:
        print(f"\n{failures} stream(s) failed - see messages above.")
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)