from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_youtube_transcript_mcp.core import extract_video_id, render_markdown, save_transcript


class TranscriptCoreTests(unittest.TestCase):
    def test_extract_video_id_from_common_youtube_urls(self) -> None:
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(extract_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_render_markdown_includes_frontmatter_and_timestamped_segments(self) -> None:
        markdown = render_markdown(
            {
                "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "video_id": "dQw4w9WgXcQ",
                "title": "Example",
                "created_at": "2026-06-28T12:00:00+00:00",
                "engine": "faster-whisper",
                "model": "large-v3",
                "language": "en",
                "segment_count": 1,
                "timestamped_transcript": "[00:00:00.000] hello world",
            }
        )
        self.assertIn("source_url: \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"", markdown)
        self.assertIn("# Example", markdown)
        self.assertIn("[00:00:00.000] hello world", markdown)

    def test_save_transcript_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = save_transcript(
                {
                    "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "video_id": "dQw4w9WgXcQ",
                    "title": "Example",
                    "created_at": "2026-06-28T12:00:00+00:00",
                    "engine": "faster-whisper",
                    "model": "large-v3",
                    "language": "en",
                    "timestamped_transcript": "[00:00:00.000] hello world",
                    "segments": [
                        {"start": 0.0, "end": 1.2, "text": "hello world"},
                    ],
                },
                {"output_dir": tmpdir},
            )

            markdown_path = Path(result["markdown_path"])
            json_path = Path(result["json_path"])
            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())
            self.assertEqual(markdown_path.parent, Path(tmpdir))
            self.assertIn("# Example", markdown_path.read_text(encoding="utf-8"))
            self.assertIn('"video_id": "dQw4w9WgXcQ"', json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
