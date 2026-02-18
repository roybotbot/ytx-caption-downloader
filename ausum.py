#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SUMMARY_INSTRUCTIONS = """Create a comprehensive markdown summary of the following transcript. Output ONLY the markdown summary, no meta-commentary.

Structure:

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
- Output the summary directly - do not describe what you would do
- Do not ask for confirmation or approval
- Start immediately with" #[Title of Youtube Video] - Summary
- Then begin first section with "## Overview" """


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


def get_output_directory() -> Path:
    """Get output directory, prompting user on first run."""
    config = load_config()
    
    # If we have a saved directory, use it
    if "output_dir" in config:
        return Path(config["output_dir"]).expanduser()
    
    # First run - prompt user
    default_dir = Path("~/Documents").expanduser()
    
    if default_dir.exists():
        prompt = f"Where should transcripts be saved? (default: {default_dir})\nPress Enter for default, or enter a path: "
    else:
        prompt = "Where should transcripts be saved? Enter a directory path: "
    
    user_input = input(prompt).strip()
    
    if user_input:
        output_dir = Path(user_input).expanduser()
    elif default_dir.exists():
        output_dir = default_dir
    else:
        print("No default directory available. Please enter a valid path.", file=sys.stderr)
        sys.exit(1)
    
    # Create directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save to config
    config["output_dir"] = str(output_dir)
    save_config(config)
    
    print(f"Saving transcripts to: {output_dir}", file=sys.stderr)
    
    return output_dir


def check_command(cmd: str) -> bool:
    """Check if a command exists on PATH."""
    return shutil.which(cmd) is not None


def check_prerequisites() -> None:
    """Verify all required tools are available."""
    missing = []
    
    if not check_command("yt-dlp"):
        missing.append("yt-dlp (install: brew install yt-dlp)")
    
    if not check_command("ffmpeg"):
        missing.append("ffmpeg (install: brew install ffmpeg)")
    
    if not check_command("swift"):
        missing.append("swift (comes with Xcode)")
    
    if not check_command("claude"):
        missing.append("claude CLI (https://docs.anthropic.com/claude-cli)")
    
    fluidaudio_path = os.environ.get("FLUIDAUDIO_PATH")
    if not fluidaudio_path:
        missing.append("FLUIDAUDIO_PATH environment variable not set")
    elif not Path(fluidaudio_path).is_dir():
        missing.append(f"FLUIDAUDIO_PATH points to non-existent directory: {fluidaudio_path}")
    elif not (Path(fluidaudio_path) / "Package.swift").exists():
        missing.append(f"No Package.swift found in FLUIDAUDIO_PATH: {fluidaudio_path}")
    
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


def get_video_title(url: str) -> str:
    """Get video title from URL."""
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "--impersonate", "chrome-131", "--print", "%(title)s", url],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "Unsupported URL" in stderr or "Unable to extract" in stderr or "no video" in stderr.lower():
            raise RuntimeError(f"No video found at URL (site may require JavaScript or use an unsupported player): {url}")
        raise RuntimeError(f"Failed to get video title: {stderr}")
    
    title = result.stdout.strip()
    return sanitize_filename(title) if title else "untitled"


def get_file_title(file_path: Path) -> str:
    """Get title from local file path (filename without extension)."""
    return sanitize_filename(file_path.stem)


def convert_local_file_to_wav(input_file: Path, output_wav: Path) -> None:
    """Convert local audio/video file to 16kHz mono WAV."""
    if not input_file.exists():
        raise RuntimeError(f"File not found: {input_file}")
    
    # Convert to 16kHz mono WAV for FluidAudio
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", str(input_file),
            "-ar", "16000",
            "-ac", "1",
            "-y",  # overwrite
            str(output_wav),
        ],
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
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "--impersonate", "chrome-131",
                "-f", "bestaudio",
                "-o", str(audio_file),
                url,
            ],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Unsupported URL" in stderr or "Unable to extract" in stderr or "no video" in stderr.lower():
                raise RuntimeError(f"No video found at URL (site may require JavaScript or use an unsupported player): {url}")
            raise RuntimeError(f"Failed to download audio: {stderr}")
        
        # Find the actual downloaded file (yt-dlp may or may not add extension)
        downloaded = None
        
        # Check without extension first
        if audio_file.exists():
            downloaded = audio_file
        else:
            # Check with common extensions
            for ext in [".m4a", ".webm", ".opus", ".mp3"]:
                candidate = Path(f"{audio_file}{ext}")
                if candidate.exists():
                    downloaded = candidate
                    break
        
        if not downloaded:
            raise RuntimeError("Audio downloaded but file not found")
        
        # Convert to 16kHz mono WAV for FluidAudio
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", str(downloaded),
                "-ar", "16000",
                "-ac", "1",
                "-y",  # overwrite
                str(output_wav),
            ],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to convert audio: {result.stderr.strip()}")


def check_parakeet_model_cache() -> bool:
    """Check if Parakeet model is already cached."""
    cache_dir = Path.home() / "Library" / "Application Support" / "FluidAudio" / "Models"
    if not cache_dir.exists():
        return False
    
    # Look for any parakeet model directory
    for item in cache_dir.iterdir():
        if item.is_dir() and "parakeet-tdt" in item.name.lower():
            return True
    
    return False


def transcribe_audio(wav_path: Path) -> str:
    """Transcribe audio using FluidAudio Parakeet."""
    fluidaudio_path = Path(os.environ["FLUIDAUDIO_PATH"])
    
    # Check if model needs downloading
    if not check_parakeet_model_cache():
        print("Downloading Parakeet model (~600MB), this only happens once...", file=sys.stderr)
    
    # Run transcription
    result = subprocess.run(
        ["swift", "run", "-c", "release", "fluidaudiocli", "transcribe", str(wav_path)],
        cwd=str(fluidaudio_path),
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Transcription failed: {result.stderr.strip()}")
    
    transcript = result.stdout.strip()
    if not transcript:
        raise RuntimeError("Transcription produced no output")
    
    return transcript


def summarize_transcript(transcript: str) -> str:
    """Summarize transcript using Claude."""
    # Build prompt
    prompt = f"{SUMMARY_INSTRUCTIONS}\n\nTranscript:\n\n{transcript}"
    
    # Run Claude in non-interactive mode with prompt via stdin
    result = subprocess.run(
        ["claude", "--print"],
        input=prompt,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Summarization failed: {result.stderr.strip()}")
    
    summary = result.stdout.strip()
    if not summary:
        raise RuntimeError("Summarization produced no output")
    
    return summary


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ausum",
        description="Transcribe and summarize audio/video files or YouTube videos using Parakeet + Claude"
    )
    parser.add_argument("input", help="YouTube URL or path to local audio/video file")
    parser.add_argument(
        "-d", "--outdir",
        help="Output directory (overrides saved preference)"
    )
    
    args = parser.parse_args()
    
    # Check prerequisites
    check_prerequisites()
    
    # Setup output directory
    if args.outdir:
        outdir = Path(args.outdir).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
    else:
        outdir = get_output_directory()
    
    # Determine if input is URL or local file
    is_remote = is_url(args.input)
    
    # Get title for filenames
    if is_remote:
        print("Getting video title...", file=sys.stderr)
        title = get_video_title(args.input)
    else:
        input_path = Path(args.input).expanduser()
        title = get_file_title(input_path)
    
    txt_path = outdir / f"{title}.txt"
    summary_path = outdir / f"{title}-summary.md"
    
    # Process audio
    with tempfile.TemporaryDirectory(prefix="ausum_") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        
        if is_remote:
            # Download and convert audio from URL
            print("Downloading and converting audio...", file=sys.stderr)
            download_and_convert_audio(args.input, wav_path)
        else:
            # Convert local file
            print("Converting audio...", file=sys.stderr)
            convert_local_file_to_wav(input_path, wav_path)
        
        # Transcribe
        print("Transcribing audio...", file=sys.stderr)
        transcript = transcribe_audio(wav_path)
    
    # Save transcript
    txt_path.write_text(transcript, encoding="utf-8")
    print("Transcript saved:", txt_path, file=sys.stderr)
    
    # Summarize
    print("Generating summary...", file=sys.stderr)
    summary = summarize_transcript(transcript)
    
    # Save summary
    summary_path.write_text(summary, encoding="utf-8")
    print("Summary saved:", summary_path, file=sys.stderr)
    
    # Print output paths
    print(str(txt_path))
    print(str(summary_path))
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"ausum: error: {e}", file=sys.stderr)
        sys.exit(1)
