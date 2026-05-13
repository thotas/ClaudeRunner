#!/usr/bin/env python3
"""
Voice Transcript Processor
Processes transcript files (VTT/SRT/plain text), splits by speaker, and generates summaries.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class TranscriptEntry:
    """Represents a single entry in a transcript."""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    speaker: Optional[str] = None
    text: str = ""


@dataclass
class SpeakerSegments:
    """Groups transcript entries by speaker."""
    speaker: str
    entries: list[TranscriptEntry] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(e.text for e in self.entries)


class TranscriptParser:
    """Parses transcript files in VTT, SRT, and plain text formats."""

    def __init__(self, config: dict):
        self.config = config
        self.patterns = [re.compile(p) for p in config.get("speaker_patterns", [])]

    def parse_file(self, filepath: str, fmt: Optional[str] = None) -> list[TranscriptEntry]:
        """Parse a transcript file and return list of entries."""
        if fmt is None:
            fmt = self._detect_format(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if fmt == "vtt":
            return self._parse_vtt(content)
        elif fmt == "srt":
            return self._parse_srt(content)
        else:
            return self._parse_plain_text(content)

    def _detect_format(self, filepath: str) -> str:
        """Detect transcript format from file extension or content."""
        ext = Path(filepath).suffix.lower()
        if ext == ".vtt":
            return "vtt"
        elif ext == ".srt":
            return "srt"
        return "text"

    def _parse_vtt(self, content: str) -> list[TranscriptEntry]:
        """Parse VTT format transcript."""
        entries = []
        lines = content.strip().split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Skip headers and empty lines
            if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
                i += 1
                continue

            # Parse timestamp line: 00:00:00.000 --> 00:00:05.000
            if "-->" in line:
                times = line.split("-->")
                start_time = times[0].strip()
                end_time = times[1].strip() if len(times) > 1 else None

                # Collect text lines until empty line
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                text = " ".join(text_lines)
                speaker = self._extract_speaker(text)
                entries.append(TranscriptEntry(
                    start_time=start_time,
                    end_time=end_time,
                    speaker=speaker,
                    text=text
                ))
            else:
                i += 1

        return entries

    def _parse_srt(self, content: str) -> list[TranscriptEntry]:
        """Parse SRT format transcript."""
        entries = []
        blocks = content.strip().split("\n\n")

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # Skip numeric index
            if lines[0].isdigit():
                lines = lines[1:]

            if len(lines) < 1:
                continue

            # Parse timestamp
            if "-->" in lines[0]:
                times = lines[0].split("-->")
                start_time = times[0].strip()
                end_time = times[1].strip() if len(times) > 1 else None
                text_lines = lines[1:]
            else:
                start_time = None
                end_time = None
                text_lines = lines

            text = " ".join(t.strip() for t in text_lines)
            speaker = self._extract_speaker(text)
            entries.append(TranscriptEntry(
                start_time=start_time,
                end_time=end_time,
                speaker=speaker,
                text=text
            ))

        return entries

    def _parse_plain_text(self, content: str) -> list[TranscriptEntry]:
        """Parse plain text transcript."""
        entries = []
        lines = content.strip().split("\n")

        current_entry: Optional[TranscriptEntry] = None

        for line in lines:
            line = line.strip()
            if not line:
                if current_entry:
                    entries.append(current_entry)
                    current_entry = None
                continue

            speaker = self._extract_speaker(line)
            if speaker:
                if current_entry:
                    entries.append(current_entry)
                current_entry = TranscriptEntry(speaker=speaker, text=line)
            else:
                if current_entry:
                    current_entry.text += " " + line
                else:
                    current_entry = TranscriptEntry(text=line)

        if current_entry:
            entries.append(current_entry)

        return entries

    def _extract_speaker(self, text: str) -> Optional[str]:
        """Extract speaker label from text using configured patterns."""
        for pattern in self.patterns:
            match = pattern.match(text)
            if match:
                if match.lastindex and match.lastindex >= 1:
                    return match.group(1) if match.lastindex == 1 else match.group(0).rstrip(":").strip()
                else:
                    return match.group(0).rstrip(":").strip()
        return None


class SpeakerSplitter:
    """Splits transcript entries by speaker."""

    def __init__(self, entries: list[TranscriptEntry]):
        self.entries = entries

    def split(self) -> list[SpeakerSegments]:
        """Group entries by speaker."""
        speaker_map: dict[str, SpeakerSegments] = {}

        for entry in self.entries:
            speaker = entry.speaker or "Unknown"
            if speaker not in speaker_map:
                speaker_map[speaker] = SpeakerSegments(speaker=speaker)
            speaker_map[speaker].entries.append(entry)

        return list(speaker_map.values())


class SummaryGenerator:
    """Generates summaries from transcript segments."""

    def __init__(self, config: dict):
        self.config = config
        self.style = config.get("summary_style", {})

    def generate_speaker_summary(self, segments: list[SpeakerSegments]) -> str:
        """Generate summary for each speaker."""
        lines = ["# Speaker Summaries\n"]

        for segment in segments:
            lines.append(f"## {segment.speaker}\n")
            lines.append(f"**Total utterances:** {len(segment.entries)}")
            lines.append(f"**Total words:** {len(segment.text.split())}\n")

            # Extract key points (simple extraction - first few sentences)
            sentences = self._split_sentences(segment.text)
            max_sentences = self.style.get("max_sentences_per_speaker", 5)
            key_points = sentences[:max_sentences]

            lines.append("**Key points:**")
            for point in key_points:
                lines.append(f"- {point}")
            lines.append("")

        return "\n".join(lines)

    def generate_full_transcript(self, entries: list[TranscriptEntry]) -> str:
        """Generate full transcript with timestamps."""
        lines = ["# Full Transcript\n"]

        for entry in entries:
            if entry.start_time:
                time_str = f"[{entry.start_time}]"
            else:
                time_str = ""

            speaker_str = f"**{entry.speaker or 'Unknown'}:**" if entry.speaker else ""
            lines.append(f"{time_str} {speaker_str} {entry.text}".strip())

        return "\n".join(lines)

    def generate_action_items(self, entries: list[TranscriptEntry]) -> str:
        """Extract action items from transcript."""
        lines = ["# Action Items\n"]
        action_items = []

        # Patterns that indicate action items
        action_patterns = [
            r"(?:TODO|FIXME|TBD|NEED TO|SHOULD|MUST|WILL|CAN|CREATE|BUILD|FIX|ADD|UPDATE|DELETE|REVIEW|COMPLETE|DONE|ASSIGN)",
            r"(?:I[' ]?ll|I will|we should|let[' ]?s|please)",
        ]

        for entry in entries:
            text = entry.text
            for pattern in action_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    # Check if it's a complete sentence that looks like an action
                    sentences = self._split_sentences(text)
                    for sent in sentences:
                        if re.search(pattern, sent, re.IGNORECASE):
                            action_items.append((entry.start_time, entry.speaker, sent))

        if action_items:
            for timestamp, speaker, item in action_items:
                time_str = f"[{timestamp}]" if timestamp else ""
                speaker_str = f"**{speaker}:**" if speaker else ""
                lines.append(f"- {time_str} {speaker_str} {item}".strip())
        else:
            lines.append("*No explicit action items detected.*")

        return "\n".join(lines)

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]


class TranscriptProcessor:
    """Main processor class."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.parser = TranscriptParser(self.config)
        self.splitter = None
        self.summarizer = SummaryGenerator(self.config)

    def process(self, filepath: str, fmt: Optional[str] = None) -> dict[str, str]:
        """Process a transcript file and generate outputs."""
        # Parse the file
        entries = self.parser.parse_file(filepath, fmt)

        # Split by speaker
        self.splitter = SpeakerSplitter(entries)
        segments = self.splitter.split()

        # Generate outputs
        input_path = Path(filepath)
        base_name = input_path.stem
        output_dir = input_path.parent
        suffix = self.config.get("output_options", {}).get("processed_suffix", "_processed")

        outputs = {}

        # Speaker summary
        if self.config.get("output_options", {}).get("include_speaker_summary", True):
            summary_path = output_dir / f"{base_name}{suffix}_summary.md"
            outputs["summary"] = str(summary_path)
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(self.summarizer.generate_speaker_summary(segments))

        # Full transcript
        if self.config.get("output_options", {}).get("include_full_transcript", True):
            transcript_path = output_dir / f"{base_name}{suffix}_transcript.md"
            outputs["transcript"] = str(transcript_path)
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(self.summarizer.generate_full_transcript(entries))

        # Action items
        if self.config.get("output_options", {}).get("include_action_items", True):
            actions_path = output_dir / f"{base_name}{suffix}_actions.md"
            outputs["actions"] = str(actions_path)
            with open(actions_path, "w", encoding="utf-8") as f:
                f.write(self.summarizer.generate_action_items(entries))

        return outputs


def main():
    parser = argparse.ArgumentParser(
        description="Voice Transcript Processor - Process transcript files with speaker splitting and summarization."
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process a transcript file")
    process_parser.add_argument("file", help="Path to transcript file")
    process_parser.add_argument(
        "--format", "-f",
        choices=["vtt", "srt", "text"],
        help="Transcript format (auto-detected if not specified)"
    )

    # Summarize command
    summarize_parser = subparsers.add_parser("summarize", help="Generate summary from transcript")
    summarize_parser.add_argument("transcript_file", help="Path to transcript file")
    summarize_parser.add_argument(
        "--format", "-f",
        choices=["vtt", "srt", "text"],
        help="Transcript format (auto-detected if not specified)"
    )

    args = parser.parse_args()

    if args.command == "process":
        processor = TranscriptProcessor()
        try:
            outputs = processor.process(args.file, args.format)
            print(f"Processed successfully. Generated files:")
            for name, path in outputs.items():
                print(f"  - {name}: {path}")
        except Exception as e:
            print(f"Error processing file: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "summarize":
        processor = TranscriptProcessor()
        try:
            entries = processor.parser.parse_file(args.transcript_file, args.format)
            segments = SpeakerSplitter(entries).split()
            print(processor.summarizer.generate_speaker_summary(segments))
        except Exception as e:
            print(f"Error generating summary: {e}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
