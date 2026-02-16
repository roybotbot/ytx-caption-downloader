# Parakeet Transcription Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a YouTube audio transcription tool using FluidAudio Parakeet + Claude summarization.

**Architecture:** CLI orchestrates yt-dlp audio extraction, ffmpeg conversion, FluidAudio transcription, and Claude summarization. All subprocess-based, no external Python dependencies.

**Tech Stack:** Python 3.10+, stdlib only, external binaries: yt-dlp, ffmpeg, swift (FluidAudio), claude

---

### Task 1: Create pyproject.toml for packaging

**Files:**
- Create: `pyproject.toml`

**Step 1: Write pyproject.toml**

```toml
[project]
name = "ytx"
version = "1.0.0"
description = "YouTube audio transcription with Parakeet + Claude summarization"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "Roy Natian"}
]

[project.scripts]
ytx = "ytx:main"

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

**Step 2: Verify file is valid**

Run: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"`
Expected: No errors (Python 3.11+) or use `pip install toml && python3 -c "import toml; toml.load('pyproject.toml')"`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add packaging configuration"
```

---

### Task 2: Create prerequisite checking utilities

**Files:**
- Create: `ytx.py`

**Step 1: Write prerequisite check functions**

```python
#!/usr/bin/env python3

import os
import shutil
import sys
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
        print("ytx: missing prerequisites:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    check_prerequisites()
    print("All prerequisites satisfied")
```

**Step 2: Test manually**

Run: `python3 ytx.py`
Expected: Either "All prerequisites satisfied" or error messages for missing tools

**Step 3: Commit**

```bash
git add ytx.py
git commit -m "feat: add prerequisite checking"
```

---

### Task 3: Add video title extraction

**Files:**
- Modify: `ytx.py`

**Step 1: Add imports and sanitization function**

Add after existing imports:

```python
import re
import subprocess
```

Add after check_prerequisites():

```python
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
```

**Step 2: Test manually**

Add to bottom of file:

```python
if __name__ == "__main__":
    check_prerequisites()
    if len(sys.argv) > 1:
        title = get_video_title(sys.argv[1])
        print(f"Title: {title}")
```

Run: `python3 ytx.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"`
Expected: Prints sanitized video title

**Step 3: Commit**

```bash
git add ytx.py
git commit -m "feat: add video title extraction and sanitization"
```

---

### Task 4: Add audio extraction and conversion

**Files:**
- Modify: `ytx.py`

**Step 1: Add tempfile import**

Add to imports:

```python
import tempfile
```

**Step 2: Add audio download and conversion functions**

Add after get_video_title():

```python
def download_and_convert_audio(url: str, output_wav: Path) -> None:
    """Download YouTube audio and convert to 16kHz mono WAV."""
    with tempfile.TemporaryDirectory(prefix="ytx_") as tmpdir:
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
        
        # Find the actual downloaded file (yt-dlp adds extension)
        downloaded = None
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
```

**Step 3: Commit**

```bash
git add ytx.py
git commit -m "feat: add audio download and WAV conversion"
```

---

### Task 5: Add Parakeet model cache detection

**Files:**
- Modify: `ytx.py`

**Step 1: Add model cache detection function**

Add after download_and_convert_audio():

```python
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
```

**Step 2: Commit**

```bash
git add ytx.py
git commit -m "feat: add Parakeet model cache detection"
```

---

### Task 6: Add transcription function

**Files:**
- Modify: `ytx.py`

**Step 1: Add transcription function**

Add after check_parakeet_model_cache():

```python
def transcribe_audio(wav_path: Path) -> str:
    """Transcribe audio using FluidAudio Parakeet."""
    fluidaudio_path = Path(os.environ["FLUIDAUDIO_PATH"])
    
    # Check if model needs downloading
    if not check_parakeet_model_cache():
        print("Downloading Parakeet model (~600MB), this only happens once...", file=sys.stderr)
    
    # Run transcription
    result = subprocess.run(
        ["swift", "run", "fluidaudio", "transcribe", str(wav_path)],
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
```

**Step 2: Commit**

```bash
git add ytx.py
git commit -m "feat: add FluidAudio Parakeet transcription"
```

---

### Task 7: Add Claude summarization

**Files:**
- Modify: `ytx.py`

**Step 1: Add summarization function**

Add after transcribe_audio():

```python
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
```

**Step 2: Commit**

```bash
git add ytx.py
git commit -m "feat: add Claude summarization"
```

---

### Task 8: Add main CLI function

**Files:**
- Modify: `ytx.py`

**Step 1: Add argparse import**

Add to imports:

```python
import argparse
```

**Step 2: Add main function**

Replace the `if __name__ == "__main__":` block with:

```python
def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ytx",
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
    with tempfile.TemporaryDirectory(prefix="ytx_") as tmpdir:
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
        print(f"ytx: error: {e}", file=sys.stderr)
        sys.exit(1)
```

**Step 3: Make executable**

Run: `chmod +x ytx.py`

**Step 4: Commit**

```bash
git add ytx.py
git commit -m "feat: add main CLI orchestration"
```

---

### Task 9: Create README documentation

**Files:**
- Create: `README.md`

**Step 1: Write README**

```markdown
# ytx - YouTube Transcription eXtractor

Automatically transcribe YouTube videos using local AI (FluidAudio Parakeet) and generate summaries with Claude.

## Features

- **Local speech-to-text** using FluidAudio's Parakeet model (600M parameters, 25 European languages)
- **Automatic summarization** with Claude, following structured format
- **Privacy-first** - all transcription runs locally on your Mac
- **Simple CLI** - one command to get transcript + summary

## Prerequisites

Install required tools:

```bash
# Package managers (one-time setup)
brew install yt-dlp ffmpeg

# Claude CLI
# Follow: https://docs.anthropic.com/claude-cli

# FluidAudio (build from source)
git clone https://github.com/FluidInference/FluidAudio.git
cd FluidAudio
swift build -c release
```

Set environment variable:

```bash
# Add to ~/.zshrc or ~/.bashrc
export FLUIDAUDIO_PATH=~/path/to/FluidAudio
```

## Installation

```bash
# Clone this repo
git clone https://github.com/roybotbot/ytx-caption-downloader.git
cd ytx-caption-downloader

# Install with pip
pip install .

# Or with pipx (recommended)
pipx install .
```

## Usage

```bash
# Basic usage (saves to ~/Documents/Transcripts/Youtube)
ytx "https://www.youtube.com/watch?v=VIDEO_ID"

# Custom output directory
ytx "https://www.youtube.com/watch?v=VIDEO_ID" -d ~/my-transcripts
```

Output files:
- `<video-title>.txt` - Full transcript
- `<video-title>-summary.md` - Structured summary

## First Run

The first time you run `ytx`, FluidAudio will download the Parakeet model (~600MB) from HuggingFace. This is cached locally and subsequent runs are much faster.

## Summary Format

Summaries follow the structure defined in `transcript-summary.md`:
- Major sections with short headers
- Concise bullet points of key points
- Step-by-step instructions (if applicable)
- Next steps for learning more

## License

MIT - See LICENSE file
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add comprehensive README"
```

---

### Task 10: Manual end-to-end test

**Files:**
- None (testing only)

**Step 1: Test with a short video**

Run: `python3 ytx.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -d /tmp/ytx-test`

Expected:
1. Video title extracted
2. Audio downloaded and converted
3. Transcription runs (model downloads on first run)
4. Transcript saved as `.txt`
5. Claude summarization runs
6. Summary saved as `-summary.md`
7. Both file paths printed to stdout

**Step 2: Verify output files**

Run: `ls -lh /tmp/ytx-test/`

Expected: Both `.txt` and `-summary.md` files present with content

**Step 3: If successful, tag release**

```bash
git tag -a v1.0.0 -m "Release: Parakeet transcription pipeline"
```

---

### Task 11: Final cleanup and merge preparation

**Files:**
- None

**Step 1: Verify all files are committed**

Run: `git status`
Expected: "nothing to commit, working tree clean"

**Step 2: Review commit history**

Run: `git log --oneline`
Expected: Clean, logical commit sequence

**Step 3: Ready for merge**

Note: Use @superpowers:finishing-a-development-branch to complete integration
