#!/usr/bin/env python3

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


POLL_LABEL = "com.ausum.poll"
POLL_INTERVAL_SECONDS = 1800
POLL_LOG_PATH = Path.home() / ".config" / "ausum" / "poll.log"

ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"

PREFERRED_FREE_MODELS = [
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
]

ZEN_FREE_MODEL_ID_EXCEPTIONS = {"big-pickle"}


def format_clickable_path(path: Path) -> str:
    """Return a shell-escaped path wrapped in an OSC 8 file hyperlink."""
    display_path = re.sub(r'([\s\\"\'\(\)\[\]\{\}&;])', r'\\\1', str(path))
    file_uri = path.resolve(strict=False).as_uri()
    return f"\033]8;;{file_uri}\033\\{display_path}\033]8;;\033\\"


SUMMARY_INSTRUCTIONS = """Create a concise filename description and comprehensive markdown summary of the following transcript. Output ONLY the filename line and markdown summary, no meta-commentary.

First output exactly one filename line:
Filename: <3-5 high-level words describing what the content is>

Then output a blank line followed by the markdown summary.

Summary structure:

1. **Overview** (bullet list)
   - High-level concepts and first principles as skimmable bullets
   - Core thesis or central argument
   - Key takeaways and why this matters
   - Each bullet should be a complete, standalone point

2. **Detailed Summary**
   - Major sections with descriptive headers
   - Under each section, detailed bullets that explain:
     * What the concept/point is
     * Why it matters
     * How it works or applies
     * Examples or context from the transcript
   - If the transcript describes building/making/producing anything, include a clear step-by-step numbered list with explanations
   - Include relevant quotes, data, or specific examples mentioned

3. **Next Steps**
   - Actionable recommendations for learning more
   - Key resources or concepts to explore further

Requirements:
- Add substance to each bullet - avoid sparse one-liners
- Stay factual - no filler or invented content
- The filename description must be content-based, not clickbait, and must not include the author
- Output the filename line and summary directly - do not describe what you would do
- Do not ask for confirmation or approval
- After the filename line and blank line, start the summary with "#[Title of Youtube Video] - Summary"
- Then begin first section with "## Overview" """


def _zen_models_http_get(url: str) -> str:
    """Fetch raw JSON text from the Zen models endpoint."""
    headers = {"User-Agent": "ausum/1.0"}
    api_key = os.environ.get("OPENCODE_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def fetch_free_models() -> list[str]:
    """Fetch the list of free model IDs from OpenCode Zen, prefixed with opencode/."""
    try:
        raw = _zen_models_http_get(ZEN_MODELS_URL)
        data = json.loads(raw)
    except Exception as exc:
        print(f"Warning: could not fetch Zen free models ({exc}); using static list only.", file=sys.stderr)
        return []

    models = data.get("data", []) if isinstance(data, dict) else []
    free_ids: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = model.get("pricing", {}) if isinstance(model.get("pricing"), dict) else {}
        input_cost = pricing.get("input")
        output_cost = pricing.get("output")
        is_free_pricing = isinstance(input_cost, (int, float)) and input_cost == 0 and isinstance(output_cost, (int, float)) and output_cost == 0
        is_free_suffix = model_id.endswith("-free") or model_id in ZEN_FREE_MODEL_ID_EXCEPTIONS
        if is_free_pricing or is_free_suffix:
            free_ids.append(f"opencode/{model_id}")
    return free_ids


def build_failover_queue() -> list[str]:
    """Build ordered failover queue: preferred static models first, then dynamic free models."""
    queue: list[str] = []
    seen: set[str] = set()
    for model in PREFERRED_FREE_MODELS:
        if model not in seen:
            queue.append(model)
            seen.add(model)
    for model in fetch_free_models():
        if model not in seen:
            queue.append(model)
            seen.add(model)
    return queue


def should_notify_pushover_for_model(model: str) -> bool:
    """Return True when a model win warrants a Pushover notification (i.e. dynamic fallback)."""
    return model not in PREFERRED_FREE_MODELS


def send_pushover(message: str, title: str = "ausum") -> int:
    """Send a Pushover notification. Returns HTTP status code, 0 on configuration/error failure."""
    user_key = os.environ.get("PUSHOVER_USER_KEY")
    app_token = os.environ.get("ASUM_PUSHOVER_APP_TOKEN")
    if not user_key or not app_token:
        print("Warning: PUSHOVER_USER_KEY or ASUM_PUSHOVER_APP_TOKEN not set; skipping notification.", file=sys.stderr)
        return 0

    payload = json.dumps({"token": app_token, "user": user_key, "message": message, "title": title}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ausum/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.getcode()
    except Exception as exc:
        print(f"Warning: Pushover notification failed ({exc}).", file=sys.stderr)
        return 0


def queue_fetch(queue_url: str, queue_token: str) -> list[dict]:
    """Fetch pending items from the remote queue."""
    req = urllib.request.Request(
        f"{queue_url.rstrip('/')}/queue",
        headers={"X-Token": queue_token, "User-Agent": "ausum/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Malformed queue payload: expected JSON object")

    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Malformed queue payload: items must be a list")

    return items


def queue_delete(queue_url: str, queue_token: str, item_id: str) -> None:
    """Delete a processed item from the remote queue."""
    encoded_item_id = quote(str(item_id), safe="")
    req = urllib.request.Request(
        f"{queue_url.rstrip('/')}/queue/{encoded_item_id}",
        method="DELETE",
        headers={"X-Token": queue_token, "User-Agent": "ausum/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()



def get_config_path() -> Path:
    """Get path to config file."""
    config_dir = Path.home() / ".config" / "ausum"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"



def load_config() -> dict:
    """Load config from file or return empty dict."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}



def save_config(config: dict) -> None:
    """Save config to file."""
    config_path = get_config_path()
    config_path.write_text(json.dumps(config, indent=2))



def resolve_dirs(config: dict) -> tuple[Path, Path]:
    """Resolve (summary_dir, transcript_dir) from config.

    If only one dir is configured, both outputs go there.
    """
    raw_summary = config.get("summary_dir") or config.get("output_dir")  # migrate old key
    raw_transcript = config.get("transcript_dir")

    if not raw_summary and not raw_transcript:
        raise RuntimeError("No output directory configured")

    summary_dir = Path(raw_summary).expanduser() if raw_summary else Path(raw_transcript).expanduser()
    transcript_dir = Path(raw_transcript).expanduser() if raw_transcript else summary_dir

    return summary_dir, transcript_dir



def get_output_dirs() -> tuple[Path, Path]:
    """Return (summary_dir, transcript_dir), prompting on first run."""
    config = load_config()

    # Migrate old single output_dir key
    if "output_dir" in config and "summary_dir" not in config:
        config["summary_dir"] = config.pop("output_dir")
        save_config(config)

    if "summary_dir" in config or "transcript_dir" in config:
        summary_dir, transcript_dir = resolve_dirs(config)
        summary_dir.mkdir(parents=True, exist_ok=True)
        transcript_dir.mkdir(parents=True, exist_ok=True)
        return summary_dir, transcript_dir

    # First run — prompt
    default_dir = Path("~/Documents").expanduser()
    default_hint = f" (default: {default_dir})" if default_dir.exists() else ""

    print("First run setup:", file=sys.stderr)

    raw = input(f"Where should summaries be saved?{default_hint}\nPress Enter for default, or enter a path: ").strip()
    if raw:
        summary_dir = Path(raw).expanduser()
    elif default_dir.exists():
        summary_dir = default_dir
    else:
        print("No default directory available. Please enter a valid path.", file=sys.stderr)
        sys.exit(1)

    raw = input("Where should transcripts be saved? (press Enter to use summary directory): ").strip()
    transcript_dir = Path(raw).expanduser() if raw else summary_dir

    raw = input("Save transcript .txt files? [Y/n]: ").strip().lower()
    save_transcript = raw != "n"

    summary_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    config["summary_dir"] = str(summary_dir)
    config["transcript_dir"] = str(transcript_dir)
    config["save_transcript"] = save_transcript
    save_config(config)

    print(f"\nSummaries → {summary_dir}", file=sys.stderr)
    print(f"Transcripts → {transcript_dir}", file=sys.stderr)
    print(f"Save transcripts: {save_transcript}", file=sys.stderr)

    return summary_dir, transcript_dir



def check_prerequisites() -> None:
    """Verify all required tools are available."""
    missing = []

    if not shutil.which("yt-dlp"):
        missing.append("yt-dlp (install: brew install yt-dlp)")

    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg (install: brew install ffmpeg)")

    if not shutil.which("pi"):
        missing.append("pi (https://github.com/mariozechner/pi-coding-agent)")

    whisper_cli = os.environ.get("WHISPER_CLI", shutil.which("whisper-cli"))
    if not whisper_cli or not Path(whisper_cli).is_file():
        missing.append("whisper-cli binary not found (set WHISPER_CLI env var or add to PATH)")

    whisper_model = os.environ.get("WHISPER_MODEL")
    if not whisper_model:
        missing.append("WHISPER_MODEL environment variable not set (path to .bin model file)")
    elif not Path(whisper_model).is_file():
        missing.append(f"WHISPER_MODEL points to non-existent file: {whisper_model}")

    if missing:
        print("ausum: missing prerequisites:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(1)



def sanitize_filename(name: str, max_len: int = 180) -> str:
    """Sanitize a string for use as a filename."""
    name = name.strip()
    name = re.sub(r'[\/:\*\?"<>\|]', "-", name)
    name = re.sub(r'\s+', " ", name)
    name = re.sub(r'\.+$', "", name)
    if not name:
        name = "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name



def is_url(input_str: str) -> bool:
    """Check if input is a URL."""
    return input_str.startswith(("http://", "https://", "www."))



def url_hostname(url: str) -> str:
    """Return lowercase hostname for a URL-like string."""
    parsed = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
    return (parsed.hostname or "").lower()



def is_instagram_url(url: str) -> bool:
    """Return True for Instagram URLs."""
    hostname = url_hostname(url)
    return hostname == "instagram.com" or hostname.endswith(".instagram.com")



def is_threads_url(url: str) -> bool:
    """Return True for Threads URLs, which are text posts and not ausum inputs."""
    hostname = url_hostname(url)
    return hostname in {"threads.com", "threads.net"} or hostname.endswith(".threads.com") or hostname.endswith(".threads.net")



def browser_cookie_source_for_url(url: str) -> str | None:
    """Return browser cookie source for yt-dlp, if configured for this URL."""
    configured = os.environ.get("AUSUM_YTDLP_COOKIES_FROM_BROWSER")
    if configured is not None:
        configured = configured.strip()
        if not configured or configured.lower() in {"0", "false", "none", "off"}:
            return None
        return configured

    if is_instagram_url(url):
        return "chrome"
    return None



def build_ytdlp_args(url: str) -> list[str]:
    """Build common yt-dlp arguments for metadata and downloads."""
    args = ["yt-dlp", "--no-warnings", "--impersonate", "chrome-131", "--no-playlist"]
    cookie_source = browser_cookie_source_for_url(url)
    if cookie_source:
        args.extend(["--cookies-from-browser", cookie_source])
    return args



def parse_author_from_url(url: str) -> str | None:
    """Extract an author-like username from URL path when present."""
    path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    for part in path_parts:
        if part.startswith("@") and len(part) > 1:
            return part[1:]
    return None



def _is_transient_ytdlp_error(stderr: str) -> bool:
    """Return True when yt-dlp stderr indicates a transient/retryable error."""
    transient_patterns = [
        "Failed to parse JSON",
        "empty media response",
    ]
    return any(p in stderr for p in transient_patterns)


def _run_ytdlp_with_retry(args: list[str], retries: int = 2, delay: int = 4) -> subprocess.CompletedProcess:
    """Run yt-dlp with retries on transient errors."""
    last_result: subprocess.CompletedProcess | None = None
    for attempt in range(retries + 1):
        result = subprocess.run(args, capture_output=True, text=True)
        last_result = result
        if result.returncode == 0:
            return result
        stderr = result.stderr or ""
        if not _is_transient_ytdlp_error(stderr):
            return result
        if attempt < retries:
            print(f"  yt-dlp transient error, retrying in {delay}s ({attempt + 1}/{retries})...", file=sys.stderr)
            time.sleep(delay)
    return last_result


def get_remote_metadata(url: str) -> dict[str, str | None]:
    """Get metadata needed for output naming from a remote URL."""
    fallback_author = parse_author_from_url(url)
    result = _run_ytdlp_with_retry(
        [*build_ytdlp_args(url), "--print", "%(uploader)s", url],
        retries=2,
        delay=4,
    )
    if result.returncode != 0:
        return {"author": fallback_author}

    author = result.stdout.strip() or fallback_author
    return {"author": author}



def get_file_title(file_path: Path) -> str:
    """Get title from local file path (filename without extension)."""
    return sanitize_filename(file_path.stem)



def convert_to_wav(input_file: Path, output_wav: Path) -> None:
    """Convert audio/video file to 16kHz mono WAV."""
    if not input_file.exists():
        raise RuntimeError(f"File not found: {input_file}")

    result = subprocess.run(
        ["ffmpeg", "-i", str(input_file), "-ar", "16000", "-ac", "1", "-y", str(output_wav)],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to convert audio: {result.stderr.strip()}")



def download_and_convert_audio(url: str, output_wav: Path) -> None:
    """Download YouTube audio and convert to 16kHz mono WAV."""
    with tempfile.TemporaryDirectory(prefix="ausum_") as tmpdir:
        # Download as best audio
        audio_file = Path(tmpdir) / "audio"
        result = _run_ytdlp_with_retry(
            [
                *build_ytdlp_args(url),
                "-f", "bestaudio/best",
                "-o", str(audio_file) + ".%(ext)s",
                url,
            ],
            retries=2,
            delay=4,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Unsupported URL" in stderr or "Unable to extract" in stderr or "no video" in stderr.lower():
                raise RuntimeError(f"No video found at URL (site may require JavaScript or use an unsupported player): {url}")
            raise RuntimeError(f"Failed to download audio: {stderr}")

        # Find the actual downloaded file (yt-dlp may or may not add extension)
        matches = list(Path(tmpdir).glob("audio*"))
        if not matches:
            raise RuntimeError("Audio downloaded but file not found")

        convert_to_wav(matches[0], output_wav)



def transcribe_audio(wav_path: Path) -> str:
    """Transcribe audio using whisper.cpp."""
    whisper_cli = os.environ.get("WHISPER_CLI") or shutil.which("whisper-cli")
    whisper_model = os.environ["WHISPER_MODEL"]

    result = subprocess.run(
        [whisper_cli, "-m", whisper_model, "-f", str(wav_path), "--output-txt", "--no-prints", "-of", str(wav_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Transcription failed: {result.stderr.strip()}")

    # whisper-cli writes <file>.txt alongside the input file
    txt_output = Path(str(wav_path) + ".txt")
    if not txt_output.exists():
        raise RuntimeError("Transcription produced no output file")

    transcript = txt_output.read_text(encoding="utf-8").strip()
    txt_output.unlink()

    if not transcript:
        raise RuntimeError("Transcription produced no output")

    return transcript



def parse_summary_response(response: str) -> tuple[str, str]:
    """Parse pi response into filename description and markdown summary."""
    lines = response.strip().splitlines()
    if not lines:
        raise RuntimeError("Summarization produced no output")

    first_line = lines[0].strip()
    if not first_line.lower().startswith("filename:"):
        return "untitled", response.strip()

    filename_description = first_line.split(":", 1)[1].strip() or "untitled"
    summary_lines = lines[1:]
    while summary_lines and not summary_lines[0].strip():
        summary_lines.pop(0)
    summary = "\n".join(summary_lines).strip()
    if not summary:
        raise RuntimeError("Summarization produced no summary")

    return sanitize_filename(filename_description, max_len=80), summary



def build_output_basename(filename_description: str, author: str | None) -> str:
    """Build sanitized output basename from LLM description and optional author."""
    parts = [filename_description]
    if author:
        parts.append(author)
    return sanitize_filename(" - ".join(parts))



def _run_pi_summary(model: str, prompt: str) -> tuple[str | None, str | None]:
    """Run one pi RPC summarization attempt.

    Returns (response_text, error_reason). On success response_text is set and error_reason is None.
    On failure response_text is None and error_reason describes why.
    """
    proc = subprocess.Popen(
        ["pi", "--model", model, "--thinking", "minimal", "--mode", "rpc", "--no-session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True
    )

    try:
        proc.stdin.write(json.dumps({"type": "prompt", "message": prompt}) + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        proc.wait()
        return None, "pi stdin closed before prompt was sent"

    chunks: list[str] = []
    error_reason: str | None = None
    saw_agent_end = False

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "message_update":
            delta = event.get("assistantMessageEvent", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                chunk = delta.get("delta", "")
                chunks.append(chunk)
                print(chunk, end="", flush=True, file=sys.stderr)
            elif delta_type == "error":
                error_reason = delta.get("reason") or delta.get("message") or "streaming error"

        if event.get("type") == "agent_end":
            saw_agent_end = True
            break

    proc.terminate()
    proc.wait()
    print(file=sys.stderr)

    response = "".join(chunks).strip()
    if error_reason:
        return None, error_reason
    if not response:
        return None, "no output" if saw_agent_end else "agent_end not received"
    return response, None


def summarize_transcript(transcript: str) -> tuple[str, str]:
    """Summarize transcript using pi via RPC mode with free-model failover."""
    prompt = f"{SUMMARY_INSTRUCTIONS}\n\nTranscript:\n\n{transcript}"

    queue = build_failover_queue()
    if not queue:
        raise RuntimeError("No summarization models available")

    failed_models: list[tuple[str, str]] = []

    for model in queue:
        print(f"Trying model: {model}", file=sys.stderr)
        response, error_reason = _run_pi_summary(model, prompt)
        if response is not None:
            filename_description, summary = parse_summary_response(response)
            print(file=sys.stderr)
            print(f"Model used: {model}", file=sys.stderr)
            if failed_models:
                print(f"Failed models: {', '.join(m for m, _ in failed_models)}", file=sys.stderr)
            if should_notify_pushover_for_model(model):
                send_pushover(
                    message=f"ausum used fallback model {model} after preferred models failed.",
                    title="ausum model failover",
                )
            return filename_description, summary

        failed_models.append((model, error_reason or "unknown error"))
        print(f"Model {model} failed: {error_reason}", file=sys.stderr)

    failure_summary = "; ".join(f"{m} ({r})" for m, r in failed_models)
    send_pushover(
        message=f"ausum: all summarization models failed. Tried: {failure_summary}",
        title="ausum all models failed",
    )
    raise RuntimeError(f"All summarization models failed: {failure_summary}")



def process_input(input_arg: str, outdir: str | None = None, read_summary: bool = False) -> int:
    """Process a URL or local file using the existing direct CLI behavior."""
    check_prerequisites()

    if outdir:
        output_dir = Path(outdir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_dir = transcript_dir = output_dir
        save_transcript = True
    else:
        summary_dir, transcript_dir = get_output_dirs()
        config = load_config()
        save_transcript = config.get("save_transcript", True)

    is_remote = is_url(input_arg)

    if is_remote:
        print("Getting video metadata...", file=sys.stderr)
        metadata = get_remote_metadata(input_arg)
        author = metadata["author"]
    else:
        input_path = Path(input_arg).expanduser()
        author = None

    with tempfile.TemporaryDirectory(prefix="ausum_") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"

        if is_remote:
            print("Downloading and converting audio...", file=sys.stderr)
            download_and_convert_audio(input_arg, wav_path)
        else:
            print("Converting audio...", file=sys.stderr)
            convert_to_wav(input_path, wav_path)

        print("Transcribing audio...", file=sys.stderr)
        transcript = transcribe_audio(wav_path)

    print("Generating summary...", file=sys.stderr)
    filename_description, summary = summarize_transcript(transcript)
    basename = build_output_basename(filename_description, author)
    txt_path = transcript_dir / f"{basename}.txt"
    summary_path = summary_dir / f"{basename}-summary.md"

    if save_transcript:
        txt_path.write_text(transcript, encoding="utf-8")
        print("Transcript saved:", format_clickable_path(txt_path), file=sys.stderr)

    source = input_arg.split("?")[0] if is_remote else input_arg
    summary = f"{summary}\n\n---\nSource: {source}"

    summary_path.write_text(summary, encoding="utf-8")
    print("Summary saved:", format_clickable_path(summary_path), file=sys.stderr)

    if save_transcript:
        print(format_clickable_path(txt_path))
    print(format_clickable_path(summary_path))

    if read_summary:
        subprocess.run(["mdv", str(summary_path)])

    return 0



def cmd_poll() -> int:
    """Process queued URLs using the standard ausum flow."""
    config = load_config()

    raw_queue_url = config.get("queue_url")
    raw_queue_token = config.get("queue_token")
    queue_url = raw_queue_url.strip() if isinstance(raw_queue_url, str) else ""
    queue_token = raw_queue_token.strip() if isinstance(raw_queue_token, str) else ""

    if not queue_url or not queue_token:
        print(
            "Error: queue_url and queue_token not configured.\n"
            f"Add them to {get_config_path()}",
            file=sys.stderr,
        )
        return 1

    try:
        summary_dir, transcript_dir = resolve_dirs(config)
        summary_dir.mkdir(parents=True, exist_ok=True)
        transcript_dir.mkdir(parents=True, exist_ok=True)
    except (RuntimeError, TypeError, ValueError):
        print(
            "Error: summary_dir/transcript_dir not configured. "
            "Configure summary_dir and transcript_dir before using poll/install-service.",
            file=sys.stderr,
        )
        return 1

    try:
        items = queue_fetch(queue_url, queue_token)
    except Exception as exc:
        print(f"Error fetching queue: {exc}", file=sys.stderr)
        send_pushover(message=f"ausum poll: failed to fetch queue: {exc}", title="ausum queue error")
        return 1

    if not isinstance(items, list):
        print("Error fetching queue: Malformed queue payload: items must be a list", file=sys.stderr)
        return 1

    if not items:
        print("No pending URLs.")
        return 0

    processed = 0
    errors = 0
    interrupted = False

    for item in items:
        if not isinstance(item, dict):
            print(f"Skipping malformed queue item: {item}", file=sys.stderr)
            errors += 1
            continue

        item_id = item.get("id")
        url = item.get("url")

        if type(item_id) not in (str, int) or not isinstance(url, str):
            print(f"Skipping malformed queue item: {item}", file=sys.stderr)
            errors += 1
            continue

        normalized_item_id = str(item_id)
        url = url.strip()

        if not normalized_item_id.strip() or not url or not is_url(url):
            print(f"Skipping malformed queue item: {item}", file=sys.stderr)
            errors += 1
            continue

        print(f"\n→ {url}", file=sys.stderr)

        if is_threads_url(url):
            print("  Skipping Threads URL; use threader for text posts.", file=sys.stderr)
            try:
                queue_delete(queue_url, queue_token, normalized_item_id)
            except Exception as exc:
                print(f"  Failed to acknowledge skipped queue item {item_id}: {exc}", file=sys.stderr)
                errors += 1
                continue
            processed += 1
            continue

        try:
            result = process_input(url)
        except KeyboardInterrupt:
            print("\nInterrupted, leaving remaining items in queue.", file=sys.stderr)
            interrupted = True
            break
        except Exception as exc:
            print(f"  Error: {exc} — will retry next poll", file=sys.stderr)
            send_pushover(message=f"ausum poll: failed to process {url}: {exc}", title="ausum processing error")
            errors += 1
            continue

        if result != 0:
            print(f"  Failed with exit code {result}, keeping item in queue", file=sys.stderr)
            send_pushover(message=f"ausum poll: processing {url} exited with code {result}", title="ausum processing error")
            errors += 1
            continue

        try:
            queue_delete(queue_url, queue_token, normalized_item_id)
        except KeyboardInterrupt:
            print("\nInterrupted, leaving remaining items in queue.", file=sys.stderr)
            interrupted = True
            break
        except Exception as exc:
            print(
                f"  Processed successfully but failed to acknowledge queue item {item_id}: {exc}",
                file=sys.stderr,
            )
            errors += 1
            continue

        processed += 1

    print(f"\nDone: {processed} processed, {errors} errors.", file=sys.stderr)
    if interrupted:
        return 130
    return 1 if errors else 0



def _ausum_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{POLL_LABEL}.plist"



def cmd_clear() -> int:
    """Delete all items from the remote queue."""
    config = load_config()

    raw_queue_url = config.get("queue_url")
    raw_queue_token = config.get("queue_token")
    queue_url = raw_queue_url.strip() if isinstance(raw_queue_url, str) else ""
    queue_token = raw_queue_token.strip() if isinstance(raw_queue_token, str) else ""

    if not queue_url or not queue_token:
        print(
            "Error: queue_url and queue_token not configured.\n"
            f"Add them to {get_config_path()}",
            file=sys.stderr,
        )
        return 1

    try:
        items = queue_fetch(queue_url, queue_token)
    except Exception as exc:
        print(f"Error fetching queue: {exc}", file=sys.stderr)
        return 1

    if not isinstance(items, list):
        print("Error: malformed queue payload", file=sys.stderr)
        return 1

    if not items:
        print("No pending URLs.")
        return 0

    deleted = 0
    errors = 0

    for item in items:
        if not isinstance(item, dict):
            print(f"Skipping malformed item: {item}", file=sys.stderr)
            errors += 1
            continue

        item_id = item.get("id")
        if type(item_id) not in (str, int) or not str(item_id).strip():
            print(f"Skipping malformed item: {item}", file=sys.stderr)
            errors += 1
            continue

        normalized = str(item_id)
        try:
            queue_delete(queue_url, queue_token, normalized)
            deleted += 1
        except Exception as exc:
            print(f"Failed to delete {normalized}: {exc}", file=sys.stderr)
            errors += 1

    print(f"Cleared {deleted} items.", file=sys.stderr)
    if errors:
        print(f"Failed to delete {errors} items.", file=sys.stderr)
        return 1
    return 0


def cmd_install_service() -> int:
    """Create a launchd plist that runs ausum poll every 30 minutes."""
    plist_path = _ausum_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    POLL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    python_bin = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    environment = {}
    for name in ("PATH", "WHISPER_CLI", "WHISPER_MODEL", "PUSHOVER_USER_KEY", "ASUM_PUSHOVER_APP_TOKEN", "OPENCODE_API_KEY"):
        value = os.environ.get(name)
        if value:
            environment[name] = value

    plist = {
        "Label": POLL_LABEL,
        "ProgramArguments": [str(python_bin), str(script_path), "poll"],
        "StartInterval": POLL_INTERVAL_SECONDS,
        "RunAtLoad": True,
        "StandardOutPath": str(POLL_LOG_PATH),
        "StandardErrorPath": str(POLL_LOG_PATH),
    }
    if environment:
        plist["EnvironmentVariables"] = environment

    plist_path.write_bytes(plistlib.dumps(plist))
    print(f"Installed: {plist_path}")
    print(f"ausum poll will run every 30 minutes. Logs at {POLL_LOG_PATH}")
    return 0



def cmd_uninstall_service() -> int:
    """Unload and remove the launchd plist."""
    plist_path = _ausum_plist_path()
    if not plist_path.exists():
        print("Not installed — nothing to remove.")
        return 0

    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    plist_path.unlink()
    print(f"Unloaded and removed {plist_path}")
    return 0



def build_command_parser() -> argparse.ArgumentParser:
    """Build parser for management subcommands."""
    parser = argparse.ArgumentParser(
        prog="ausum",
        description="Transcribe and summarize audio/video files or YouTube videos using whisper.cpp + pi"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("poll", help="Process URLs queued from your phone")
    subparsers.add_parser("install-service", help="Install launchd plist for auto-polling")
    subparsers.add_parser("uninstall-service", help="Remove launchd plist")
    subparsers.add_parser("clear", help="Delete all pending items from the queue")
    return parser



def build_legacy_parser() -> argparse.ArgumentParser:
    """Build parser for the original direct CLI form."""
    parser = argparse.ArgumentParser(
        prog="ausum",
        description="Transcribe and summarize audio/video files or YouTube videos using whisper.cpp + pi"
    )
    parser.add_argument("input", help="YouTube URL or path to local audio/video file")
    parser.add_argument(
        "-d", "--outdir",
        help="Output directory (overrides saved preference)"
    )
    parser.add_argument(
        "--read",
        action="store_true",
        help="Open the summary in mdv after it's created"
    )
    return parser



def print_main_help() -> None:
    """Print direct CLI help plus discoverable management subcommands."""
    build_legacy_parser().print_help()
    print("\nCommands:")
    print("  poll               Process URLs queued from your phone")
    print("  install-service    Install launchd plist for auto-polling")
    print("  uninstall-service  Remove launchd plist")
    print("  clear              Delete all pending items from the queue")



def should_run_subcommand(first_arg: str, command_names: set[str]) -> bool:
    """Return True only when the arg is a command name and not an existing local path."""
    if first_arg not in command_names:
        return False
    return not Path(first_arg).expanduser().exists()



def main() -> int:
    """Main CLI entry point."""
    argv = sys.argv[1:]
    command_names = {"poll", "install-service", "uninstall-service", "clear"}

    if argv and argv[0] in {"-h", "--help"}:
        print_main_help()
        return 0

    if argv and should_run_subcommand(argv[0], command_names):
        args = build_command_parser().parse_args(argv)

        if args.command == "poll":
            return cmd_poll()
        if args.command == "install-service":
            return cmd_install_service()
        if args.command == "uninstall-service":
            return cmd_uninstall_service()
        if args.command == "clear":
            return cmd_clear()

    args = build_legacy_parser().parse_args(argv)
    return process_input(args.input, outdir=args.outdir, read_summary=args.read)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"ausum: error: {e}", file=sys.stderr)
        sys.exit(1)
