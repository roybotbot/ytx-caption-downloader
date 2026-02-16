#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


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


def get_video_title(url: str) -> str:
    """Get video title from YouTube URL."""
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "--print", "%(title)s", url],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get video title: {result.stderr.strip()}")
    
    title = result.stdout.strip()
    return sanitize_filename(title) if title else "untitled"


def download_and_convert_audio(url: str, output_wav: Path) -> None:
    """Download YouTube audio and convert to 16kHz mono WAV."""
    with tempfile.TemporaryDirectory(prefix="ausum_") as tmpdir:
        # Download as best audio
        audio_file = Path(tmpdir) / "audio"
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "-f", "bestaudio",
                "-o", str(audio_file),
                url,
            ],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to download audio: {result.stderr.strip()}")
        
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
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
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
    # Load summary instructions
    instructions_file = Path(__file__).parent / "transcript-summary.md"
    if not instructions_file.exists():
        raise RuntimeError(f"Summary instructions not found: {instructions_file}")
    
    instructions = instructions_file.read_text()
    
    # Build prompt
    prompt = f"{instructions}\n\nTranscript:\n\n{transcript}"
    
    # Run Claude
    result = subprocess.run(
        ["claude", "-p", prompt],
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
        description="YouTube audio transcription with Parakeet + Claude summarization"
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument(
        "-d", "--outdir",
        help="Output directory (default: ~/Documents/Transcripts/Youtube)"
    )
    
    args = parser.parse_args()
    
    # Check prerequisites
    check_prerequisites()
    
    # Setup output directory
    if args.outdir:
        outdir = Path(args.outdir).expanduser()
    else:
        outdir = Path("~/Documents/Transcripts/Youtube").expanduser()
    
    outdir.mkdir(parents=True, exist_ok=True)
    
    # Get video title for filenames
    print("Getting video title...", file=sys.stderr)
    title = get_video_title(args.url)
    
    txt_path = outdir / f"{title}.txt"
    summary_path = outdir / f"{title}-summary.md"
    
    # Download and convert audio
    print("Downloading and converting audio...", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="ausum_") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        download_and_convert_audio(args.url, wav_path)
        
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
