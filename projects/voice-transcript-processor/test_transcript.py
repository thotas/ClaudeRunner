#!/usr/bin/env python3
"""
Tests for Voice Transcript Processor
"""

import os
import sys
import tempfile
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from transcript_processor import (
    TranscriptEntry,
    TranscriptParser,
    SpeakerSplitter,
    SummaryGenerator,
    TranscriptProcessor,
)


class TestVTTParsing(unittest.TestCase):
    """Tests for VTT format parsing."""

    def setUp(self):
        self.config = {
            "speaker_patterns": [
                "^SPEAKER_(\\d+):",
                "^\\[([^\\]]+)\\]",
                "^<([^>]+)>",
                "^([A-Z][a-z]+):",
            ],
            "summary_style": {
                "format": "bullets",
                "max_sentences_per_speaker": 5,
                "include_action_items": True,
            },
            "output_options": {
                "processed_suffix": "_processed",
                "include_speaker_summary": True,
                "include_full_transcript": True,
                "include_action_items": True,
            },
        }

    def test_parse_simple_vtt(self):
        """Test parsing a simple VTT file."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
SPEAKER_1: Hello everyone, welcome to the meeting.

00:00:05.000 --> 00:00:10.000
SPEAKER_2: Thank you for having me.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "vtt")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].speaker, "1")
            self.assertEqual(entries[0].text, "SPEAKER_1: Hello everyone, welcome to the meeting.")
            self.assertEqual(entries[1].speaker, "2")
            self.assertEqual(entries[1].text, "SPEAKER_2: Thank you for having me.")
        finally:
            os.unlink(filepath)

    def test_parse_vtt_with_brackets(self):
        """Test parsing VTT with bracket-style speaker labels."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
[Moderator] Good morning everyone.

00:00:05.000 --> 00:00:10.000
[Alice] Good morning.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "vtt")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].speaker, "Moderator")
            self.assertEqual(entries[1].speaker, "Alice")
        finally:
            os.unlink(filepath)

    def test_parse_vtt_multiline(self):
        """Test parsing VTT with multiline entries."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:10.000
SPEAKER_1: This is line one.
This is line two.
This is line three.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "vtt")
            self.assertEqual(len(entries), 1)
            self.assertIn("line one", entries[0].text)
            self.assertIn("line two", entries[0].text)
            self.assertIn("line three", entries[0].text)
        finally:
            os.unlink(filepath)


class TestSRTParsing(unittest.TestCase):
    """Tests for SRT format parsing."""

    def setUp(self):
        self.config = {
            "speaker_patterns": [
                "^SPEAKER_(\\d+):",
                "^\\[([^\\]]+)\\]",
                "^([A-Z][a-z]+):",
            ],
            "summary_style": {"format": "bullets", "max_sentences_per_speaker": 5},
            "output_options": {
                "processed_suffix": "_processed",
                "include_speaker_summary": True,
                "include_full_transcript": True,
                "include_action_items": True,
            },
        }

    def test_parse_simple_srt(self):
        """Test parsing a simple SRT file."""
        srt_content = """1
00:00:00,000 --> 00:00:05,000
SPEAKER_1: Hello everyone.

2
00:00:05,000 --> 00:00:10,000
SPEAKER_2: Hi there.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(srt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "srt")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].speaker, "1")
            self.assertEqual(entries[1].speaker, "2")
        finally:
            os.unlink(filepath)

    def test_parse_srt_with_brackets(self):
        """Test parsing SRT with bracket-style speaker labels."""
        srt_content = """1
00:00:00,000 --> 00:00:05,000
[Moderator] Welcome to the call.

2
00:00:05,000 --> 00:00:10,000
[John] Thank you.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(srt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "srt")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].speaker, "Moderator")
            self.assertEqual(entries[1].speaker, "John")
        finally:
            os.unlink(filepath)

    def test_parse_srt_without_timestamps(self):
        """Test parsing SRT entries without timestamps (just numbered)."""
        srt_content = """1
SPEAKER_1: Just text content.

2
SPEAKER_2: More text content.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(srt_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "srt")
            self.assertEqual(len(entries), 2)
        finally:
            os.unlink(filepath)


class TestPlainTextParsing(unittest.TestCase):
    """Tests for plain text format parsing."""

    def setUp(self):
        self.config = {
            "speaker_patterns": [
                "^SPEAKER_(\\d+):",
                "^\\[([^\\]]+)\\]",
                "^([A-Z][a-z]+):",
            ],
            "summary_style": {"format": "bullets", "max_sentences_per_speaker": 5},
            "output_options": {
                "processed_suffix": "_processed",
                "include_speaker_summary": True,
                "include_full_transcript": True,
                "include_action_items": True,
            },
        }

    def test_parse_plain_text_with_speakers(self):
        """Test parsing plain text with speaker labels."""
        text_content = """John: Hello, how are you?
Mary: I'm doing well, thanks.
John: Great to hear that."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "text")
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[0].speaker, "John")
            self.assertEqual(entries[1].speaker, "Mary")
            self.assertEqual(entries[2].speaker, "John")
        finally:
            os.unlink(filepath)

    def test_parse_plain_text_without_speakers(self):
        """Test parsing plain text without speaker labels."""
        text_content = """This is a single block of text.
It continues on multiple lines.
But it's all one speaker."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text_content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "text")
            self.assertEqual(len(entries), 1)
            self.assertIsNone(entries[0].speaker)
        finally:
            os.unlink(filepath)


class TestSpeakerSplitting(unittest.TestCase):
    """Tests for speaker splitting functionality."""

    def setUp(self):
        self.config = {
            "speaker_patterns": ["^([A-Z][a-z]+):"],
            "summary_style": {"format": "bullets", "max_sentences_per_speaker": 5},
            "output_options": {},
        }

    def test_split_by_speaker(self):
        """Test splitting entries by speaker."""
        entries = [
            TranscriptEntry(speaker="Alice", text="Hello."),
            TranscriptEntry(speaker="Bob", text="Hi there."),
            TranscriptEntry(speaker="Alice", text="How are you?"),
            TranscriptEntry(speaker="Bob", text="I'm fine."),
        ]
        splitter = SpeakerSplitter(entries)
        segments = splitter.split()

        self.assertEqual(len(segments), 2)
        speakers = {s.speaker for s in segments}
        self.assertEqual(speakers, {"Alice", "Bob"})

        alice_segment = next(s for s in segments if s.speaker == "Alice")
        self.assertEqual(len(alice_segment.entries), 2)

        bob_segment = next(s for s in segments if s.speaker == "Bob")
        self.assertEqual(len(bob_segment.entries), 2)

    def test_split_with_unknown_speaker(self):
        """Test splitting with entries that have no speaker."""
        entries = [
            TranscriptEntry(speaker=None, text="No speaker label."),
            TranscriptEntry(speaker="Alice", text="I have a label."),
        ]
        splitter = SpeakerSplitter(entries)
        segments = splitter.split()

        self.assertEqual(len(segments), 2)
        speakers = {s.speaker for s in segments}
        self.assertIn("Unknown", speakers)
        self.assertIn("Alice", speakers)

    def test_segment_text_property(self):
        """Test that SpeakerSegments.text combines all entry texts."""
        entries = [
            TranscriptEntry(speaker="Alice", text="First part."),
            TranscriptEntry(speaker="Alice", text="Second part."),
        ]
        splitter = SpeakerSplitter(entries)
        segments = splitter.split()

        self.assertEqual(len(segments), 1)
        self.assertIn("First part", segments[0].text)
        self.assertIn("Second part", segments[0].text)


class TestSummaryGeneration(unittest.TestCase):
    """Tests for summary generation."""

    def setUp(self):
        self.config = {
            "summary_style": {
                "format": "bullets",
                "max_sentences_per_speaker": 2,
                "include_action_items": True,
            },
            "output_options": {},
        }

    def test_generate_speaker_summary(self):
        """Test generating speaker summary."""
        segments = [
            SpeakerSplitter([
                TranscriptEntry(speaker="Alice", text="Hello everyone. This is Alice speaking."),
            ]).split()[0],
            SpeakerSplitter([
                TranscriptEntry(speaker="Bob", text="Hi Alice. Bob here with a question."),
            ]).split()[0],
        ]
        # Re-create properly
        from transcript_processor import SpeakerSegments
        seg1 = SpeakerSegments(speaker="Alice")
        seg1.entries = [TranscriptEntry(speaker="Alice", text="Hello everyone. This is Alice speaking.")]
        seg2 = SpeakerSegments(speaker="Bob")
        seg2.entries = [TranscriptEntry(speaker="Bob", text="Hi Alice. Bob here with a question.")]

        generator = SummaryGenerator(self.config)
        summary = generator.generate_speaker_summary([seg1, seg2])

        self.assertIn("Alice", summary)
        self.assertIn("Bob", summary)
        self.assertIn("utterances", summary)

    def test_generate_full_transcript(self):
        """Test generating full transcript with timestamps."""
        entries = [
            TranscriptEntry(start_time="00:00:00", end_time="00:00:05", speaker="Alice", text="Hello."),
            TranscriptEntry(start_time="00:00:05", end_time="00:00:10", speaker="Bob", text="Hi."),
        ]
        generator = SummaryGenerator(self.config)
        transcript = generator.generate_full_transcript(entries)

        self.assertIn("00:00:00", transcript)
        self.assertIn("Alice", transcript)
        self.assertIn("Hello", transcript)

    def test_generate_action_items(self):
        """Test extracting action items."""
        entries = [
            TranscriptEntry(start_time="00:00:00", speaker="Alice", text="I will send the report tomorrow."),
            TranscriptEntry(start_time="00:00:05", speaker="Bob", text="Let's schedule a follow-up."),
            TranscriptEntry(start_time="00:00:10", speaker="Alice", text="We should review the budget."),
        ]
        generator = SummaryGenerator(self.config)
        actions = generator.generate_action_items(entries)

        self.assertIn("Action Items", actions)
        # Action items should contain entries with will/should
        self.assertTrue(
            "send the report" in actions or "tomorrow" in actions or "review the budget" in actions
        )


class TestTranscriptProcessor(unittest.TestCase):
    """Integration tests for TranscriptProcessor."""

    def setUp(self):
        self.config = {
            "speaker_patterns": [
                "^SPEAKER_(\\d+):",
                "^\\[([^\\]]+)\\]",
                "^([A-Z][a-z]+):",
            ],
            "summary_style": {
                "format": "bullets",
                "max_sentences_per_speaker": 5,
                "include_action_items": True,
            },
            "output_options": {
                "processed_suffix": "_processed",
                "include_speaker_summary": True,
                "include_full_transcript": True,
                "include_action_items": True,
            },
        }

    def test_process_vtt_file(self):
        """Test processing a VTT file end-to-end."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
[Alice] Hello, let's discuss the project.

00:00:05.000 --> 00:00:10.000
[Bob] Sure, I have some ideas.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False, dir="/tmp") as f:
            f.write(vtt_content)
            filepath = f.name

        try:
            import json

            config_dir = tempfile.mkdtemp()
            config_path = os.path.join(config_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(self.config, f)

            processor = TranscriptProcessor(config_path)
            outputs = processor.process(filepath)

            self.assertIn("summary", outputs)
            self.assertIn("transcript", outputs)
            self.assertIn("actions", outputs)

            # Verify output files exist
            for name, path in outputs.items():
                self.assertTrue(os.path.exists(path), f"Output file {path} should exist")
                with open(path, "r") as f:
                    content = f.read()
                    self.assertGreater(len(content), 0, f"{name} should have content")

            # Cleanup output files
            for path in outputs.values():
                os.unlink(path)
            os.unlink(config_path)
            os.rmdir(config_dir)
        finally:
            os.unlink(filepath)

    def test_process_srt_file(self):
        """Test processing an SRT file end-to-end."""
        srt_content = """1
00:00:00,000 --> 00:00:05,000
SPEAKER_1: This is a test.

2
00:00:05,000 --> 00:00:10,000
SPEAKER_2: Yes it is.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, dir="/tmp") as f:
            f.write(srt_content)
            filepath = f.name

        try:
            import json

            config_dir = tempfile.mkdtemp()
            config_path = os.path.join(config_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(self.config, f)

            processor = TranscriptProcessor(config_path)
            outputs = processor.process(filepath)

            self.assertEqual(len(outputs), 3)

            for path in outputs.values():
                self.assertTrue(os.path.exists(path))
                os.unlink(path)
            os.unlink(config_path)
            os.rmdir(config_dir)
        finally:
            os.unlink(filepath)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases."""

    def setUp(self):
        self.config = {
            "speaker_patterns": ["^([A-Z][a-z]+):"],
            "summary_style": {"format": "bullets", "max_sentences_per_speaker": 5},
            "output_options": {
                "processed_suffix": "_processed",
                "include_speaker_summary": True,
                "include_full_transcript": True,
                "include_action_items": True,
            },
        }

    def test_empty_file(self):
        """Test handling of empty file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "text")
            self.assertEqual(len(entries), 0)
        finally:
            os.unlink(filepath)

    def test_whitespace_only(self):
        """Test handling of whitespace-only content."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write("\n\n   \n\t\n")
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "vtt")
            self.assertEqual(len(entries), 0)
        finally:
            os.unlink(filepath)

    def test_no_matching_speaker_pattern(self):
        """Test parsing when no speaker pattern matches."""
        content = "Just plain text without any speaker markers."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            filepath = f.name

        try:
            parser = TranscriptParser(self.config)
            entries = parser.parse_file(filepath, "text")
            self.assertEqual(len(entries), 1)
            self.assertIsNone(entries[0].speaker)
        finally:
            os.unlink(filepath)


if __name__ == "__main__":
    unittest.main()
