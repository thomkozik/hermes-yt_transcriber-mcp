from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .core import (
    download_youtube_audio as _download_youtube_audio,
    save_transcript as _save_transcript,
    transcribe_audio as _transcribe_audio,
    transcribe_youtube as _transcribe_youtube,
)

mcp = FastMCP("hermes-youtube-transcript")


@mcp.tool(name="download_youtube_audio")
def download_youtube_audio(url_or_video_id: str) -> dict[str, Any]:
    """Download the best available YouTube audio to a local cache path."""

    return _download_youtube_audio(url_or_video_id)


@mcp.tool(name="transcribe_audio")
def transcribe_audio(file_path: str) -> dict[str, Any]:
    """Normalize an audio file with ffmpeg and transcribe it with faster-whisper."""

    return _transcribe_audio(file_path)


@mcp.tool(name="transcribe_youtube")
def transcribe_youtube(url_or_video_id: str) -> dict[str, Any]:
    """Download a YouTube video, normalize the audio, and transcribe it STT-first."""

    return _transcribe_youtube(url_or_video_id)


@mcp.tool(name="save_transcript")
def save_transcript(transcript: Any, metadata: Any | None = None) -> dict[str, Any]:
    """Persist a transcript as durable Markdown plus JSON sidecar for Obsidian/Thorn."""

    return _save_transcript(transcript, metadata)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
