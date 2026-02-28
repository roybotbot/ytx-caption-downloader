# ausum - Audio Summarization

Automatically transcribe and summarize any audio or video file using local AI (FluidAudio Parakeet) + Claude. Works with YouTube videos, podcasts, recordings, meetings, lectures - any audio content.

This is a tool built for macOS.

## Why?

Reading is faster than watching videos. For certain types of videos I find it faster to read a detailed summary versus watching the video at a faster speed.

## Features

- **Local speech-to-text** using FluidAudio's Parakeet model (600M parameters, 25 European languages)
- **Automatic summarization** with Claude (falls back to pi if claude is unavailable or not logged in)
- **Privacy-first** - all transcription runs locally on your Mac
- **Simple CLI** - one command to get transcript + summary

## Prerequisites

Install required tools:

```bash
# Package managers (one-time setup)
brew install yt-dlp ffmpeg

# Claude CLI (recommended)
# Follow: https://docs.anthropic.com/claude-cli

# OR pi (used as automatic fallback if claude is unavailable or not logged in)
# Follow: https://github.com/mariozechner/pi

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
git clone https://github.com/roybotbot/ausum.git
cd ausum

# Install with pip
pip install .

# Or with pipx (recommended)
pipx install .
```

## Usage

```bash
# YouTube videos
ausum "https://www.youtube.com/watch?v=VIDEO_ID"

# Local audio/video files
ausum /path/to/video.mp4
ausum ~/Downloads/podcast.mp3
ausum ./recording.wav

# Override saved directory for a single run
ausum "https://www.youtube.com/watch?v=VIDEO_ID" -d ~/my-transcripts
```

**Supported formats:** Any audio or video format that ffmpeg can read (mp4, mp3, wav, m4a, webm, mkv, avi, flac, ogg, etc.)

Output files:
- `<video-title>.txt` or `<filename>.txt` - Full transcript
- `<video-title>-summary.md` or `<filename>-summary.md` - Structured summary

## First Run

On your first run, `ausum` will:
1. Ask where you'd like to save transcripts (defaults to `~/Documents` if it exists)
2. Save your preference to `~/.config/ausum/config.json`
3. Download the Parakeet model (~600MB) from HuggingFace

Subsequent runs use your saved directory preference. You can always override it with `-d`.

## Model Storage

The Parakeet model (~460MB) is cached in `~/Library/Application Support/FluidAudio/Models/` and persists across ausum updates. It is NOT deleted when you reinstall ausum with pipx - the cache is managed by FluidAudio, not ausum.

If you need to free up disk space, you can manually delete the cache:
```bash
rm -rf ~/Library/Application\ Support/FluidAudio/Models/parakeet*
```

The model will be re-downloaded on next use.

## Summary Format

Summaries follow the structure defined in `transcript-summary.md`:
- Major sections with short headers
- Concise bullet points of key points
- Step-by-step instructions (if applicable)
- Next steps for learning more

## License

MIT - See LICENSE file
