# ausum - Audio Summarization

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
ausum "https://www.youtube.com/watch?v=VIDEO_ID"

# Custom output directory
ausum "https://www.youtube.com/watch?v=VIDEO_ID" -d ~/my-transcripts
```

Output files:
- `<video-title>.txt` - Full transcript
- `<video-title>-summary.md` - Structured summary

## First Run

The first time you run `ausum`, FluidAudio will download the Parakeet model (~600MB) from HuggingFace. This is cached locally and subsequent runs are much faster.

## Summary Format

Summaries follow the structure defined in `transcript-summary.md`:
- Major sections with short headers
- Concise bullet points of key points
- Step-by-step instructions (if applicable)
- Next steps for learning more

## License

MIT - See LICENSE file
