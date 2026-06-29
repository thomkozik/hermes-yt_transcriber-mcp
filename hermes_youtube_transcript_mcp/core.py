from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DEFAULT_MODEL = "large-v3"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"
CACHE_DIR_NAME = "hermes-youtube-transcript-mcp"
TRANSCRIPT_DIR_ENV = "HERMES_YT_TRANSCRIPTS_DIR"
DOWNLOAD_DIR_ENV = "HERMES_YT_DOWNLOAD_DIR"
NORMALIZED_DIR_ENV = "HERMES_YT_NORMALIZED_DIR"
WHISPER_MODEL_ENV = "HERMES_YT_WHISPER_MODEL"
WHISPER_DEVICE_ENV = "HERMES_YT_WHISPER_DEVICE"
WHISPER_COMPUTE_ENV = "HERMES_YT_WHISPER_COMPUTE_TYPE"
WHISPER_BEAM_ENV = "HERMES_YT_WHISPER_BEAM_SIZE"


@dataclass
class TranscriptBundle:
    source_url: str
    video_id: str
    title: str | None
    created_at: str
    engine: str
    model: str
    language: str | None
    language_probability: float | None
    transcript: str
    timestamped_transcript: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    downloaded_audio_path: str | None = None
    normalized_audio_path: str | None = None
    download_dir: str | None = None
    segment_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "video_id": self.video_id,
            "title": self.title,
            "created_at": self.created_at,
            "engine": self.engine,
            "model": self.model,
            "language": self.language,
            "language_probability": self.language_probability,
            "transcript": self.transcript,
            "timestamped_transcript": self.timestamped_transcript,
            "segments": self.segments,
            "downloaded_audio_path": self.downloaded_audio_path,
            "normalized_audio_path": self.normalized_audio_path,
            "download_dir": self.download_dir,
            "segment_count": self.segment_count,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cache_root() -> Path:
    return Path.home() / ".local" / "share" / CACHE_DIR_NAME


def download_root() -> Path:
    return Path(os.getenv(DOWNLOAD_DIR_ENV, str(cache_root() / "downloads"))).expanduser()


def normalized_root() -> Path:
    return Path(os.getenv(NORMALIZED_DIR_ENV, str(cache_root() / "normalized"))).expanduser()


def transcripts_root() -> Path:
    default_root = cache_root() / "transcripts"
    return Path(os.getenv(TRANSCRIPT_DIR_ENV, str(default_root))).expanduser()


def ensure_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"Required command '{name}' was not found on PATH. Install it before using this server."
        )


def ensure_python_package(package_name: str, import_name: str | None = None) -> None:
    module_name = import_name or package_name
    try:
        __import__(module_name)
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError(
            f"Required Python package '{package_name}' is not installed. "
            f"Install the project dependencies with 'uv sync' or 'uv pip install {package_name}'."
        ) from exc


def extract_video_id(url_or_video_id: str) -> str:
    value = url_or_video_id.strip()
    if YOUTUBE_VIDEO_ID_RE.fullmatch(value):
        return value

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        path_parts = [part for part in parsed.path.split("/") if part]

        if "youtu.be" in host and path_parts:
            candidate = path_parts[0]
            if YOUTUBE_VIDEO_ID_RE.fullmatch(candidate):
                return candidate

        if "youtube.com" in host:
            query = parse_qs(parsed.query)
            candidate = query.get("v", [None])[0]
            if candidate and YOUTUBE_VIDEO_ID_RE.fullmatch(candidate):
                return candidate

            for marker in ("shorts", "embed", "live", "clip"):
                if marker in path_parts:
                    index = path_parts.index(marker)
                    if index + 1 < len(path_parts):
                        candidate = path_parts[index + 1]
                        if YOUTUBE_VIDEO_ID_RE.fullmatch(candidate):
                            return candidate

            if path_parts and path_parts[0] == "watch":
                candidate = query.get("v", [None])[0]
                if candidate and YOUTUBE_VIDEO_ID_RE.fullmatch(candidate):
                    return candidate

    match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", value)
    if match:
        return match.group(1)

    raise ValueError(
        "Could not resolve a YouTube video ID from the supplied value. "
        "Pass a standard YouTube URL or an 11-character video ID."
    )


def canonical_youtube_url(url_or_video_id: str) -> tuple[str, str]:
    video_id = extract_video_id(url_or_video_id)
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def sanitize_filename(value: str, fallback: str = "transcript") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-._")
    return cleaned or fallback


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def _locate_downloaded_file(download_dir: Path, video_id: str) -> Path:
    candidates = sorted(
        download_dir.glob(f"{video_id}.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    raise RuntimeError(
        f"yt-dlp completed but no downloaded file matching '{video_id}.*' was found in {download_dir}."
    )


def download_youtube_audio(url_or_video_id: str) -> dict[str, Any]:
    ensure_python_package("yt-dlp", "yt_dlp")
    ensure_binary("ffmpeg")

    from yt_dlp import YoutubeDL

    source_url, video_id = canonical_youtube_url(url_or_video_id)
    root = download_root()
    root.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(root / "%(id)s.%(ext)s"),
        "overwrites": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=True)

    downloaded_path = _locate_downloaded_file(root, info.get("id") or video_id)

    return {
        "source_url": info.get("webpage_url") or source_url,
        "video_id": info.get("id") or video_id,
        "title": info.get("title"),
        "channel": info.get("channel"),
        "uploader": info.get("uploader"),
        "duration_seconds": info.get("duration"),
        "downloaded_audio_path": str(downloaded_path),
        "download_dir": str(root),
        "downloaded_at": utc_now_iso(),
    }


def normalize_audio(file_path: str | Path) -> Path:
    ensure_binary("ffmpeg")
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Audio file not found: {source}")

    root = normalized_root()
    root.mkdir(parents=True, exist_ok=True)
    normalized = root / f"{source.stem}.normalized.wav"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-map_metadata",
        "-1",
        str(normalized),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed while normalizing the audio. "
            f"stderr: {result.stderr.strip() or 'no stderr'}"
        )

    return normalized


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    ensure_python_package("faster-whisper", "faster_whisper")
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _build_transcript_segments(segments_iter) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    segments: list[dict[str, Any]] = []
    transcript_lines: list[str] = []
    transcript_parts: list[str] = []

    for segment in segments_iter:
        text = segment.text.strip()
        words = []
        for word in getattr(segment, "words", []) or []:
            words.append(
                {
                    "start": round(float(word.start), 3),
                    "end": round(float(word.end), 3),
                    "word": word.word,
                }
            )

        entry: dict[str, Any] = {
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": text,
        }
        if words:
            entry["words"] = words
        segments.append(entry)
        transcript_parts.append(text)
        transcript_lines.append(f"[{format_timestamp(segment.start)}] {text}")

    return segments, transcript_parts, transcript_lines


def transcribe_audio(file_path: str) -> dict[str, Any]:
    ensure_binary("ffmpeg")
    normalized = normalize_audio(file_path)

    model_name = os.getenv(WHISPER_MODEL_ENV, DEFAULT_MODEL)
    device = os.getenv(WHISPER_DEVICE_ENV, DEFAULT_DEVICE)
    compute_type = os.getenv(WHISPER_COMPUTE_ENV, DEFAULT_COMPUTE_TYPE)
    beam_size = int(os.getenv(WHISPER_BEAM_ENV, "5"))

    model = _load_model(model_name, device, compute_type)
    segments_iter, info = model.transcribe(
        str(normalized),
        beam_size=beam_size,
        vad_filter=True,
        word_timestamps=True,
    )

    segments, transcript_parts, transcript_lines = _build_transcript_segments(segments_iter)
    transcript = " ".join(part for part in transcript_parts if part).strip()
    timestamped = "\n".join(transcript_lines).strip()

    if not transcript:
        raise RuntimeError(
            "The STT engine completed but returned no transcript text. "
            "Check whether the audio contains speech or whether the model needs a different device/compute setting."
        )

    language = getattr(info, "language", None)
    language_probability = getattr(info, "language_probability", None)

    return {
        "created_at": utc_now_iso(),
        "engine": "faster-whisper",
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "language": language,
        "language_probability": round(float(language_probability), 4) if language_probability is not None else None,
        "normalized_audio_path": str(normalized),
        "source_path": str(Path(file_path).expanduser().resolve()),
        "segments": segments,
        "transcript": transcript,
        "timestamped_transcript": timestamped,
        "segment_count": len(segments),
    }


def transcribe_youtube(url_or_video_id: str) -> dict[str, Any]:
    download_info = download_youtube_audio(url_or_video_id)
    transcript_info = transcribe_audio(download_info["downloaded_audio_path"])
    return {
        **download_info,
        **transcript_info,
        "source_url": download_info["source_url"],
        "video_id": download_info["video_id"],
        "title": download_info.get("title"),
        "downloaded_audio_path": download_info["downloaded_audio_path"],
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _build_frontmatter(record: dict[str, Any]) -> str:
    keys = [
        "source_url",
        "video_id",
        "title",
        "created_at",
        "engine",
        "model",
        "device",
        "compute_type",
        "language",
        "language_probability",
        "segment_count",
        "downloaded_audio_path",
        "normalized_audio_path",
    ]
    lines = ["---"]
    for key in keys:
        if key not in record or record[key] is None:
            continue
        lines.append(f"{key}: {_yaml_scalar(record[key])}")
    lines.append("---")
    return "\n".join(lines)


def render_markdown(record: dict[str, Any]) -> str:
    title = record.get("title") or record.get("video_id") or "YouTube transcript"
    transcript_body = record.get("timestamped_transcript") or record.get("transcript") or ""
    frontmatter = _build_frontmatter(record)

    parts = [
        frontmatter,
        "",
        f"# {title}",
        "",
        f"- Source: {record.get('source_url', '')}",
        f"- Video ID: `{record.get('video_id', '')}`",
        f"- Created: {record.get('created_at', '')}",
        f"- Engine: {record.get('engine', '')} ({record.get('model', '')})",
        f"- Language: {record.get('language', 'unknown')}",
    ]

    if record.get("downloaded_audio_path"):
        parts.append(f"- Downloaded audio: `{record['downloaded_audio_path']}`")
    if record.get("normalized_audio_path"):
        parts.append(f"- Normalized audio: `{record['normalized_audio_path']}`")

    parts.extend([
        "",
        "## Transcript",
        "",
        transcript_body,
        "",
    ])
    return "\n".join(parts).rstrip() + "\n"


def _coerce_record(transcript: Any, metadata: Any | None) -> dict[str, Any]:
    record: dict[str, Any]
    if isinstance(transcript, dict):
        record = dict(transcript)
    elif isinstance(transcript, str):
        try:
            parsed = json.loads(transcript)
            record = parsed if isinstance(parsed, dict) else {"transcript": transcript}
        except Exception:
            record = {"transcript": transcript}
    else:
        record = {"transcript": str(transcript)}

    if metadata is None:
        metadata = {}
    elif isinstance(metadata, str):
        try:
            parsed_metadata = json.loads(metadata)
            metadata = parsed_metadata if isinstance(parsed_metadata, dict) else {}
        except Exception:
            metadata = {}
    elif not isinstance(metadata, dict):
        metadata = {"metadata": metadata}

    record.update(metadata)
    record.setdefault("created_at", utc_now_iso())
    record.setdefault("engine", record.get("engine") or "faster-whisper")
    record.setdefault("model", record.get("model") or DEFAULT_MODEL)
    record.setdefault("source_url", record.get("source_url") or record.get("url") or "")
    record.setdefault("video_id", record.get("video_id") or record.get("id") or "")
    record.setdefault("title", record.get("title") or record.get("name") or "")
    return record


def save_transcript(transcript: Any, metadata: Any | None = None) -> dict[str, Any]:
    record = _coerce_record(transcript, metadata)
    output_dir_value = record.pop("output_dir", None)
    output_dir = Path(output_dir_value or transcripts_root()).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    created_date = record["created_at"][:10]
    title_slug = sanitize_filename(record.get("title") or record.get("video_id") or "transcript")
    video_id = sanitize_filename(record.get("video_id") or "video")
    stem = f"{created_date}_{title_slug}_{video_id}"

    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"

    record["markdown_path"] = str(markdown_path)
    record["json_path"] = str(json_path)

    markdown_path.write_text(render_markdown(record), encoding="utf-8")
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "saved_at": utc_now_iso(),
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "output_dir": str(output_dir),
        "record": record,
    }
