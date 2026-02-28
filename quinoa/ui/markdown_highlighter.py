"""Markdown syntax highlighter for QPlainTextEdit.

Based on patterns from ReText's highlighter:
https://github.com/retext-project/retext
"""

import re

from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


class MarkdownHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Markdown text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_formats()
        self._setup_rules()

    def _setup_formats(self) -> None:
        """Setup text formats for different Markdown elements."""
        # Header format (bold, larger)
        self.header_format = QTextCharFormat()
        self.header_format.setFontWeight(QFont.Weight.Bold)
        self.header_format.setForeground(QColor("#0066cc"))

        # Bold format
        self.bold_format = QTextCharFormat()
        self.bold_format.setFontWeight(QFont.Weight.Bold)

        # Italic format
        self.italic_format = QTextCharFormat()
        self.italic_format.setFontItalic(True)

        # Bold italic format
        self.bold_italic_format = QTextCharFormat()
        self.bold_italic_format.setFontWeight(QFont.Weight.Bold)
        self.bold_italic_format.setFontItalic(True)

        # Code format (monospace, background)
        self.code_format = QTextCharFormat()
        self.code_format.setFontFamily("monospace")
        self.code_format.setBackground(QColor("#f0f0f0"))
        self.code_format.setForeground(QColor("#c7254e"))

        # Link format
        self.link_format = QTextCharFormat()
        self.link_format.setForeground(QColor("#0066cc"))
        self.link_format.setFontUnderline(True)

        # Link URL format (dimmed)
        self.link_url_format = QTextCharFormat()
        self.link_url_format.setForeground(QColor("#999999"))

        # List format
        self.list_format = QTextCharFormat()
        self.list_format.setForeground(QColor("#666666"))

        # Blockquote format
        self.blockquote_format = QTextCharFormat()
        self.blockquote_format.setForeground(QColor("#666666"))
        self.blockquote_format.setFontItalic(True)

        # Strikethrough format
        self.strikethrough_format = QTextCharFormat()
        self.strikethrough_format.setFontStrikeOut(True)

        # Horizontal rule format
        self.hr_format = QTextCharFormat()
        self.hr_format.setForeground(QColor("#cccccc"))

    def _setup_rules(self) -> None:
        """Setup highlighting rules with regex patterns."""
        self.rules: list[tuple[re.Pattern, QTextCharFormat, int]] = []

        # Headers: # Header, ## Header, etc.
        # Match from start of line
        self.rules.append((re.compile(r"^#{1,6}\s+.+$", re.MULTILINE), self.header_format, 0))

        # Bold italic: ***text*** or ___text___
        self.rules.append(
            (re.compile(r"(\*{3}|_{3})(?!\s)(.+?)(?<!\s)\1"), self.bold_italic_format, 0)
        )

        # Bold: **text** or __text__
        self.rules.append((re.compile(r"(\*{2}|_{2})(?!\s)(.+?)(?<!\s)\1"), self.bold_format, 0))

        # Italic: *text* or _text_ (but not inside words for _)
        self.rules.append(
            (re.compile(r"(?<!\w)\*(?!\s)([^*]+?)(?<!\s)\*(?!\w)"), self.italic_format, 0)
        )
        self.rules.append(
            (re.compile(r"(?<!\w)_(?!\s)([^_]+?)(?<!\s)_(?!\w)"), self.italic_format, 0)
        )

        # Strikethrough: ~~text~~
        self.rules.append((re.compile(r"~~(?!\s)(.+?)(?<!\s)~~"), self.strikethrough_format, 0))

        # Inline code: `code`
        self.rules.append((re.compile(r"`[^`]+`"), self.code_format, 0))

        # Links: [text](url)
        self.rules.append((re.compile(r"\[([^\]]+)\]\([^\)]+\)"), self.link_format, 0))

        # Unordered lists: - item, * item, + item
        self.rules.append((re.compile(r"^\s*[-*+]\s+", re.MULTILINE), self.list_format, 0))

        # Ordered lists: 1. item, 2. item, etc.
        self.rules.append((re.compile(r"^\s*\d+\.\s+", re.MULTILINE), self.list_format, 0))

        # Blockquotes: > text
        self.rules.append((re.compile(r"^\s*>+\s*.*$", re.MULTILINE), self.blockquote_format, 0))

        # Horizontal rules: ---, ***, ___
        self.rules.append((re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE), self.hr_format, 0))

    def highlightBlock(self, text: str | None) -> None:
        """Apply syntax highlighting to a block of text."""
        if text is None:
            return

        # Apply each rule
        for pattern, fmt, _group in self.rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - match.start()
                self.setFormat(start, length, fmt)

        # Handle multi-line code blocks
        self._highlight_code_blocks(text)

    def _highlight_code_blocks(self, text: str) -> None:
        """Handle multi-line fenced code blocks (```)."""
        # State: 0 = normal, 1 = inside code block
        code_block_state = 1

        # Check if previous block was in a code block
        prev_state = self.previousBlockState()
        in_code_block = prev_state == code_block_state

        # Check for code fence in current line
        fence_pattern = re.compile(r"^```")
        fence_match = fence_pattern.match(text)

        if fence_match:
            # Found a fence - toggle state
            if in_code_block:
                # End of code block
                self.setFormat(0, len(text), self.code_format)
                self.setCurrentBlockState(0)
            else:
                # Start of code block
                self.setFormat(0, len(text), self.code_format)
                self.setCurrentBlockState(code_block_state)
        elif in_code_block:
            # Inside code block - format entire line
            self.setFormat(0, len(text), self.code_format)
            self.setCurrentBlockState(code_block_state)
        else:
            # Not in code block
            self.setCurrentBlockState(0)
