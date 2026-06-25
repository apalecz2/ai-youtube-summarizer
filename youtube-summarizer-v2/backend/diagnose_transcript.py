#!/usr/bin/env python3
"""Standalone transcript-fetch diagnostic.

Runs the EXACT yt-dlp path the app uses (same cookies / proxy / impersonate from
your .env, via fetcher._base_opts) against one or more videos and reports, step by
step, *where* transcript fetching breaks and *why* — distinguishing a YouTube IP
rate-limit (429) from a genuinely caption-less video.

It only reads; it never touches the database, queue, or email.

Usage (run inside the backend env / container so yt_dlp + .env are loaded):
    python diagnose_transcript.py <video_id_or_url> [more...]
    python diagnose_transcript.py -hRxUJy1Uk4
    python diagnose_transcript.py -v https://www.youtube.com/watch?v=r4xoOQ32KNM

    # In Docker:
    docker compose exec backend python diagnose_transcript.py <url>

Flags:
    -v / --verbose   Show full yt-dlp logging (drops the quiet flags).
    --no-download    Stop after listing caption tracks (skip the subtitle fetch).

Exit code is 0 if every video yielded a transcript, else 1 — handy for scripting.
"""
import sys

import yt_dlp

from app import config
from app.youtube import fetcher, gate


def _hr(char: str = "─") -> str:
    return char * 64


def _yn(value: bool) -> str:
    return "yes" if value else "no"


def print_environment() -> None:
    print(_hr("="))
    print("ENVIRONMENT")
    print(_hr("="))
    cookies = config.YTDLP_COOKIES_FILE
    import os
    cookies_ok = bool(cookies and os.path.exists(cookies))
    print(f"  cookies file      : {cookies or '(none)'}  -> exists: {_yn(cookies_ok)}")
    print(f"  proxy (YTDLP_PROXY): {config.YTDLP_PROXY or '(none)'}")
    print(f"  impersonate        : {config.YTDLP_IMPERSONATE or '(none)'}")
    # Is curl_cffi (needed for impersonation) importable?
    try:
        import curl_cffi  # noqa: F401
        print("  curl_cffi          : installed")
    except Exception:
        print("  curl_cffi          : NOT installed (impersonation will be ignored)")
    print(f"  yt-dlp version     : {yt_dlp.version.__version__}")
    print()


# Player clients worth trying when the app's default ("web") returns no captions.
# YouTube serves caption tracks differently per client; "web" is the most likely to
# be stripped (PO-token gating), while mobile/tv clients often still include them.
_PROBE_CLIENTS = ["web", "mweb", "web_safari", "tv", "android", "ios"]


def probe_player_clients(vid: str, *, verbose: bool) -> list[str]:
    """When the default client returns no captions, re-run extract_info under each
    candidate client and report which ones expose caption tracks. The winner is
    what fetcher._base_opts should use."""
    print("[probe] No captions from the app's default client — trying alternates")
    print("        (whichever returns tracks is what fetcher should switch to):")
    winners: list[str] = []
    for client in _PROBE_CLIENTS:
        opts = fetcher._base_opts()
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        if not verbose:
            opts.update(quiet=True, no_warnings=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            langs = fetcher.available_caption_langs(info)
            n = len(langs["manual"]) + len(langs["automatic"])
            if n:
                winners.append(client)
            print(f"        {client:12s}: {n:3d} tracks   manual={langs['manual'] or '-'}   "
                  f"auto={langs['automatic'][:8] or '-'}")
        except Exception as e:  # noqa: BLE001
            print(f"        {client:12s}: ERROR {type(e).__name__}: {str(e)[:70]}")
    print()
    if winners:
        print(f"    => RECOMMENDATION: set player_client to {winners} in")
        print(f"       app/youtube/fetcher.py -> _base_opts (extractor_args.youtube.player_client).")
    else:
        print("    => No client exposed captions. More likely a PO-token/IP issue, or the")
        print("       video genuinely has none. Try with cookies + impersonation on a clean IP.")
    print()
    return winners


def classify_body(raw: bytes, url: str) -> str:
    """Mirror fetcher's heuristic so the verdict matches what the app would do."""
    if not raw:
        return "EMPTY"
    head = raw[:512].lstrip().lower()
    looks_like_captions = (
        b'"events"' in raw[:2000] or b"webvtt" in head or url.find("fmt=json3") != -1
    )
    if looks_like_captions:
        return "CAPTIONS"
    if head.startswith(b"<") or b"too many requests" in head:
        return "NON-CAPTION (HTML/error page)"
    return "UNKNOWN (not caption-shaped)"


def diagnose(video: str, *, verbose: bool, do_download: bool) -> bool:
    """Returns True if a transcript was successfully obtained."""
    vid = fetcher.extract_video_id(video) or video
    print(_hr("="))
    print(f"VIDEO: {video}")
    print(f"  resolved video_id: {vid}")
    print(_hr("="))

    # ── Step 1: metadata extract_info ──
    print("[1] extract_info (metadata + caption track listing)…")
    opts = fetcher._base_opts()
    if verbose:
        opts.update({"quiet": False, "no_warnings": False, "logger": None})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    except Exception as e:  # noqa: BLE001
        blocked = gate.is_block_error(e)
        print(f"    FAILED: {type(e).__name__}: {e}")
        print(f"    -> classified as: {'RATE-LIMIT / BOT BLOCK' if blocked else 'video unavailable / other'}")
        print(f"    VERDICT: {'RATE-LIMITED at metadata step' if blocked else 'metadata fetch failed'}\n")
        return False

    meta = fetcher.metadata_from_info(info)
    print(f"    OK — title   : {meta['title']}")
    print(f"         channel : {meta['channel']}")
    print(f"         duration: {meta['duration']}s   live_status: {meta['live_status']}")

    # ── Step 2: caption availability ──
    langs = fetcher.available_caption_langs(info)
    print("[2] caption tracks advertised in metadata:")
    print(f"    manual    : {', '.join(langs['manual']) or '(none)'}")
    print(f"    automatic : {', '.join(langs['automatic']) or '(none)'}")

    # ── Step 3: which track the app would pick ──
    pick = fetcher._pick_subtitle_track(info)
    if not pick:
        print("[3] track selection: NONE matched our English preference list.")
        if not langs["manual"] and not langs["automatic"]:
            print("    No caption tracks at all under the app's default client.\n")
            winners = probe_player_clients(vid, verbose=verbose)
            if winners:
                print("    VERDICT: WRONG PLAYER CLIENT — captions exist via "
                      f"{winners}, but not the app's 'web' client. Fix is a config change, "
                      "not a different IP.\n")
            else:
                print("    VERDICT: NO CAPTIONS from any client (PO-token/IP block, or none exist).\n")
        else:
            print("    VERDICT: captions exist but none are English-ish. Genuinely no usable transcript.\n")
        return False
    lang, source, url = pick
    print(f"[3] track selection: lang='{lang}' source='{source}'")
    print(f"    url: {url[:100]}…")

    if not do_download:
        print("    (--no-download given; stopping before the subtitle fetch)\n")
        return False

    # ── Step 4: actually download the subtitle file ──
    print("[4] downloading the subtitle file (the step that 429s on a flagged IP)…")
    try:
        with yt_dlp.YoutubeDL(fetcher._base_opts()) as ydl:  # type: ignore
            resp = ydl.urlopen(url)
            status = getattr(resp, "status", None)
            raw = resp.read()
    except Exception as e:  # noqa: BLE001
        blocked = gate.is_block_error(e)
        print(f"    DOWNLOAD FAILED: {type(e).__name__}: {e}")
        print(f"    VERDICT: {'RATE-LIMITED (429) on subtitle download' if blocked else 'subtitle download error'}\n")
        return False

    kind = classify_body(raw, url)
    print(f"    HTTP status: {status}   bytes: {len(raw)}   shape: {kind}")
    print(f"    first 80 bytes: {raw[:80]!r}")

    if kind == "CAPTIONS":
        result = fetcher.fetch_transcript_from_info(info)
        if result and result.get("text"):
            text = result["text"]
            print(f"    PARSED OK — {len(text)} chars, lang={result['lang']}, source={result['source']}")
            print(f"    preview: {text[:160]}…")
            print("    VERDICT: SUCCESS ✅\n")
            return True
        print("    Downloaded captions but parsed to empty text.")
        print("    VERDICT: empty transcript (unusual — check the parser / track)\n")
        return False

    # Non-caption body with a real track selected == almost certainly rate-limited.
    print("    A caption track was selected but the server returned non-caption data.")
    print("    VERDICT: RATE-LIMITED ⛔ — Google's subtitle server is 429'ing this IP.")
    print("             The video DOES have a transcript; the fix is a different egress IP")
    print("             (set YTDLP_PROXY, or use Cloudflare WARP / a relay VPS).\n")
    return False


def parse_args(argv: list[str]) -> tuple[list[str], bool, bool]:
    """Hand-rolled parsing so video IDs that start with '-' (very common on
    YouTube, e.g. -hRxUJy1Uk4) aren't mistaken for option flags by argparse."""
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        sys.exit(0)
    verbose = False
    no_download = False
    videos: list[str] = []
    for tok in argv:
        if tok in ("-v", "--verbose"):
            verbose = True
        elif tok == "--no-download":
            no_download = True
        elif tok == "--":
            continue
        else:
            videos.append(tok)
    if not videos:
        print("usage: diagnose_transcript.py [-v] [--no-download] <video_id_or_url> [more...]")
        print("  (video IDs may start with '-', e.g.  diagnose_transcript.py -hRxUJy1Uk4)")
        sys.exit(2)
    return videos, verbose, no_download


def main() -> int:
    videos, verbose, no_download = parse_args(sys.argv[1:])

    print_environment()
    results = [diagnose(v, verbose=verbose, do_download=not no_download) for v in videos]

    ok = sum(results)
    print(_hr("="))
    print(f"SUMMARY: {ok}/{len(results)} video(s) produced a transcript.")
    print(_hr("="))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
