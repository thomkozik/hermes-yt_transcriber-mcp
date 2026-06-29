# Hermes YouTube Transcript MCP Server

A Hermes-ready MCP server for **STT-first** YouTube transcript ingestion.
It downloads audio with `yt-dlp`, normalizes it with `ffmpeg`, transcribes it
with `faster-whisper`, and saves durable Markdown + JSON outputs suitable for
Obsidian and Hermes ingestion.

## Exposed tools

- `download_youtube_audio(url_or_video_id)`
- `transcribe_audio(file_path)`
- `transcribe_youtube(url_or_video_id)`
- `save_transcript(transcript, metadata)`

## Why this stack

- **`yt-dlp`**: reliable YouTube audio fetcher
- **`ffmpeg`**: normalizes audio before transcription
- **`faster-whisper`**: high-quality local STT engine
- **MCP stdio**: Hermes can discover and call the tools directly

YouTube captions are **not** used as the primary transcript source here.
They can be added later as a fallback or comparison step, but this server is
STT-first by design.

## Install

### 1) System dependencies

Install these first:

- `ffmpeg`
- `uv`

If you want `faster-whisper` to use GPU acceleration, install the relevant
CUDA/metal stack for your machine. The server defaults to CPU-friendly settings
and can be tuned with environment variables.

### 2) Python dependencies

From this directory:

```bash
uv sync
```

If you prefer a one-off environment install:

```bash
uv pip install -e .
```

## Run the MCP server

```bash
uv run python -m hermes_youtube_transcript_mcp.server
```

That starts the server over stdio, which is the best fit for Hermes MCP.

## Hermes MCP config

Add this to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  youtube_transcripts:
    command: "uv"
    args:
      - "run"
      - "--project"
      - "/Users/thomkozik/dev/hermes-youtube-transcript-mcp"
      - "python"
      - "-m"
      - "hermes_youtube_transcript_mcp.server"
    timeout: 300
    connect_timeout: 60
```

After saving the config, restart Hermes or reload MCP so the tools are
rediscovered. In Hermes, the tools should appear with the prefix:

- `mcp_youtube_transcripts_download_youtube_audio`
- `mcp_youtube_transcripts_transcribe_audio`
- `mcp_youtube_transcripts_transcribe_youtube`
- `mcp_youtube_transcripts_save_transcript`

You can confirm discovery with:

```bash
hermes mcp list
hermes mcp test youtube_transcripts
```

## Environment variables

Optional overrides:

- `HERMES_YT_TRANSCRIPTS_DIR`: where Markdown/JSON transcript files are saved
- `HERMES_YT_DOWNLOAD_DIR`: where raw downloads are cached
- `HERMES_YT_NORMALIZED_DIR`: where normalized WAV files are written
- `HERMES_YT_WHISPER_MODEL`: `large-v3` by default
- `HERMES_YT_WHISPER_DEVICE`: `cpu` by default
- `HERMES_YT_WHISPER_COMPUTE_TYPE`: `int8` by default
- `HERMES_YT_WHISPER_BEAM_SIZE`: `5` by default

## Output format

`save_transcript()` writes two files:

1. Markdown with YAML frontmatter and a human-readable transcript body
2. JSON sidecar with the full metadata and segment list

This format is durable, grep-friendly, and easy to ingest into Obsidian or
Thorn.

## Verification

Run the unit tests:

```bash
uv run python -m unittest discover -s tests -v
```

If you want a manual smoke test after config is loaded, use Hermes to call
`mcp_youtube_transcripts_transcribe_youtube` on a known public video and check
that the Markdown and JSON files are created in the configured output directory.

## Notes

- If `ffmpeg` is missing, the server raises a clear error before transcription.
- If `yt-dlp` or `faster-whisper` are missing, the server tells you how to
  install the project dependencies.
- This implementation intentionally avoids relying on YouTube captions as the
  primary transcript source.
