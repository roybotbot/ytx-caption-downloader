# ausum - Audio Summarization

Automatically transcribe and summarize any audio or video file using local transcription (whisper.cpp) and AI summarization via pi (with kimi-k2.5 model). Works with YouTube videos, podcasts, recordings, meetings, lectures - any audio content.

This is a tool built for macOS.

## Why?

Reading is faster than watching videos. For certain types of videos I find it faster to read a detailed summary versus watching the video at a faster speed.

## Features

- **Local speech-to-text** using [whisper.cpp](https://github.com/ggml-org/whisper.cpp) with Metal GPU acceleration
- **AI summarization** via pi using kimi-k2.5 model with live streaming output
- **Privacy-first** - all transcription runs locally on your Mac
- **Simple CLI** - one command to get transcript + summary

## Prerequisites

Install required tools:

```bash
# Package managers (one-time setup)
brew install yt-dlp ffmpeg

# pi (install via instructions at https://github.com/mariozechner/pi-coding-agent)
# Make sure `pi` is in your PATH

# whisper.cpp (build from source)
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release

# Download a whisper model
bash models/download-ggml-model.sh large-v3-turbo
```

Set environment variables:

```bash
# Add to ~/.zshrc or ~/.bashrc

# whisper.cpp
export WHISPER_CLI=~/path/to/whisper.cpp/build/bin/whisper-cli
export WHISPER_MODEL=~/path/to/whisper.cpp/models/ggml-large-v3-turbo.bin
```

## Installation

```bash
# Clone this repo
git clone https://github.com/roybotbot/ausum.git
cd ausum

# Install with pipx (recommended)
pipx install .

# Or with pip
pip install .
```

## Usage

```bash
# YouTube videos
ausum "https://www.youtube.com/watch?v=VIDEO_ID"

# YouTube videos with playlist in URL (only processes the single video)
ausum "https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID"

# Local audio/video files
ausum /path/to/video.mp4
ausum ~/Downloads/podcast.mp3
ausum ./recording.wav

# Override saved directory for a single run
ausum "https://www.youtube.com/watch?v=VIDEO_ID" -d ~/my-transcripts

# Open summary in mdv after creation
ausum "https://www.youtube.com/watch?v=VIDEO_ID" --read
```

**Supported formats:** Any audio or video format that ffmpeg can read (mp4, mp3, wav, m4a, webm, mkv, avi, flac, ogg, etc.)

Output files use a 3-5 word LLM-generated content description. Remote URLs append the author/uploader; local files omit author.
- `<description> - <author>.txt` - Full transcript for remote URLs
- `<description> - <author>-summary.md` - Structured summary for remote URLs
- `<description>.txt` - Full transcript for local files
- `<description>-summary.md` - Structured summary for local files

## First Run

On your first run, `ausum` will:
1. Ask where summaries should be saved (defaults to `~/Documents` if it exists)
2. Ask where transcripts should be saved (press Enter to use the same directory)
3. Ask whether to save transcript `.txt` files at all

Subsequent runs use your saved preferences. You can override the output directory per-run with the `-d` flag.

## Configuration

Preferences are stored in `~/.config/ausum/config.json`. You can edit it directly:

```json
{
  "summary_dir": "/path/to/summaries",
  "transcript_dir": "/path/to/transcripts",
  "save_transcript": true
}
```

- **`summary_dir`** — where `.md` summary files are saved
- **`transcript_dir`** — where `.txt` transcript files are saved (optional; if omitted, uses `summary_dir`)
- **`save_transcript`** — set to `false` to skip saving the raw transcript

## Summary Format

Summaries follow a structured format:
- **Overview** — bullet list of high-level concepts and key takeaways
- **Detailed Summary** — major sections with descriptive headers and detailed bullets
- **Next Steps** — actionable recommendations for learning more

Each summary includes a source link at the bottom.

## Instagram and Threads

Instagram reels use browser cookies by default via `yt-dlp --cookies-from-browser chrome` because Instagram often blocks anonymous downloads. Override the browser with `AUSUM_YTDLP_COOKIES_FROM_BROWSER`, or set it to `none` to disable browser cookies.

Threads text posts are not video/audio inputs. `ausum poll` skips and acknowledges Threads URLs so they do not retry forever; use `threader` for Threads posts.

## Queue (iOS Shortcut)

ausum can process URLs queued from your phone via a Cloudflare Worker.

### Configure queue credentials

Add to `~/.config/ausum/config.json`:

```json
{
  "summary_dir": "~/Documents/Ausum",
  "queue_url": "https://nom-noms.roy-natian.workers.dev/ausum",
  "queue_token": "your-secret-token"
}
```

### Commands

```bash
ausum poll              # Process all queued URLs now
ausum install-service   # Auto-poll every 30 minutes (launchd)
ausum uninstall-service # Remove auto-poll
```

Logs: `~/.config/ausum/poll.log`

## License

MIT - See LICENSE file
