#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_OUTDIR = Path("~/Documents/Transcripts/Youtube").expanduser()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
	return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def sanitize_filename(name: str, max_len: int = 180) -> str:
	# keep it simple + mac-friendly
	name = name.strip()
	name = re.sub(r"[\/:\*\?\"<>\|]", "-", name)      # forbidden on common filesystems
	name = re.sub(r"\s+", " ", name)
	name = re.sub(r"\.+$", "", name)                 # no trailing dots
	if not name:
		name = "untitled"
	if len(name) > max_len:
		name = name[:max_len].rstrip()
	return name


def get_title(url: str) -> str:
	# Try to get a clean title from yt-dlp
	p = run(["yt-dlp", "--no-warnings", "--print", "%(title)s", url])
	title = (p.stdout or "").strip()
	if p.returncode == 0 and title:
		return title
	# fallback: something stable-ish
	return "youtube-video"


def find_caption_file(tmpdir: Path, lang: str) -> Path | None:
	# yt-dlp writes files like:
	#   "Video Title.en.vtt" or "Video Title.en-US.vtt" etc.
	vtts = sorted(tmpdir.glob("*.vtt"))
	if not vtts:
		return None

	# Prefer exact lang match if present, else take first
	# (Often you'll get multiple; keep behavior predictable.)
	lang_lower = lang.lower()
	exact = [p for p in vtts if f".{lang_lower}." in p.name.lower() or p.name.lower().endswith(f".{lang_lower}.vtt")]
	if exact:
		return exact[0]
	return vtts[0]


def vtt_to_text(vtt_content: str) -> str:
	lines = vtt_content.splitlines()
	out = []
	for line in lines:
		s = line.strip()
		if not s:
			continue
		if s.startswith("WEBVTT"):
			continue
		if re.match(r"^\d+$", s):  # cue index
			continue
		if "-->" in s:  # timestamp line
			continue
		# remove basic tags like <c>, </c>, <i>, etc.
		s = re.sub(r"<[^>]+>", "", s)
		# unescape common HTML-ish entities
		s = (s.replace("&nbsp;", " ")
			   .replace("&amp;", "&")
			   .replace("&lt;", "<")
			   .replace("&gt;", ">"))
		if s:
			out.append(s)

	# de-dupe consecutive repeats (common in captions)
	cleaned = []
	prev = None
	for s in out:
		if s != prev:
			cleaned.append(s)
		prev = s

	return "\n".join(cleaned).strip() + "\n" if cleaned else ""


def fetch_audio(url: str, outdir: Path, title: str) -> Path:
	"""Download audio as m4a using yt-dlp."""
	audio_path = outdir / f"{title}.m4a"
	cmd = [
		"yt-dlp",
		"--no-warnings",
		"-f", "bestaudio[ext=m4a]/bestaudio",
		"--extract-audio",
		"--audio-format", "m4a",
		"-o", str(audio_path),
		url,
	]
	p = run(cmd)
	if p.returncode != 0:
		raise RuntimeError(p.stderr.strip() or "Failed to download audio")
	
	# yt-dlp may add extension, find the actual file
	if audio_path.exists():
		return audio_path
	# Check for alternative extensions yt-dlp might produce
	for ext in [".m4a", ".mp3", ".opus", ".webm"]:
		alt = outdir / f"{title}{ext}"
		if alt.exists():
			return alt
	raise RuntimeError("Audio download completed but file not found")


def fetch_captions_vtt(url: str, lang: str, tmpdir: Path) -> Path:
	"""
	Try:
	  1) human-provided subs
	  2) auto subs
	Always writes into tmpdir using yt-dlp output template.
	"""
	outtmpl = str(tmpdir / "%(title)s.%(language)s.%(ext)s")

	common = [
		"yt-dlp",
		"--no-warnings",
		"--skip-download",
		"--write-subs",
		"--sub-langs", lang,
		"--sub-format", "vtt",
		"-o", outtmpl,
		url,
	]

	p1 = run(common)
	if p1.returncode == 0:
		f = find_caption_file(tmpdir, lang)
		if f:
			return f

	# fallback: auto captions
	common_auto = [
		"yt-dlp",
		"--no-warnings",
		"--skip-download",
		"--write-auto-subs",
		"--sub-langs", lang,
		"--sub-format", "vtt",
		"-o", outtmpl,
		url,
	]
	p2 = run(common_auto)
	if p2.returncode == 0:
		f = find_caption_file(tmpdir, lang)
		if f:
			return f

	# If we got here, give a useful error
	err = (p1.stderr.strip() or p2.stderr.strip() or "No subtitles found (and no yt-dlp error output).")
	raise RuntimeError(err)


def main() -> int:
	ap = argparse.ArgumentParser(
		prog="ytx",
		description="Download YouTube captions and save as a plain .txt transcript.",
	)
	ap.add_argument("url", help="YouTube URL")
	ap.add_argument("-o", "--outdir", help="Output directory (default: ~/Documents/Transcripts/Youtube)")
	ap.add_argument("-l", "--lang", default="en", help="Subtitle language (default: en)")
	ap.add_argument("-a", "--audio", action="store_true", help="Also download audio file")
	ap.add_argument("--keep-vtt", action="store_true", help="Also save the .vtt next to the .txt")

	args = ap.parse_args()

	outdir = Path(args.outdir).expanduser() if args.outdir else DEFAULT_OUTDIR
	outdir.mkdir(parents=True, exist_ok=True)

	title = sanitize_filename(get_title(args.url))
	txt_path = outdir / f"{title}.txt"
	vtt_path_final = outdir / f"{title}.vtt"

	with tempfile.TemporaryDirectory(prefix="ytx_") as td:
		tmpdir = Path(td)
		vtt_path = fetch_captions_vtt(args.url, args.lang, tmpdir)
		vtt_content = vtt_path.read_text(encoding="utf-8", errors="replace")
		txt = vtt_to_text(vtt_content)

		if not txt.strip():
			raise RuntimeError("Downloaded captions, but parsed transcript is empty.")

		txt_path.write_text(txt, encoding="utf-8")
		if args.keep_vtt:
			vtt_path_final.write_text(vtt_content, encoding="utf-8")

	# Download audio if requested (outside tempdir context)
	audio_path = None
	if args.audio:
		audio_path = fetch_audio(args.url, outdir, title)

	print(str(txt_path))
	if audio_path:
		print(str(audio_path))
	return 0


if __name__ == "__main__":
	try:
		raise SystemExit(main())
	except KeyboardInterrupt:
		raise SystemExit(130)
	except Exception as e:
		print(f"ytx: error: {e}", file=sys.stderr)
		raise SystemExit(1)