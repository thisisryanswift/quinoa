"""WYSIWYG Markdown editor with formatting toolbar."""

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
)
from PyQt6.QtWidgets import (
    QMenu,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from quinoa.ui.markdown_converter import html_to_markdown, markdown_to_html


class RichTextEditor(QWidget):
    """WYSIWYG markdown editor with formatting toolbar.

    Displays formatted text (WYSIWYG) while saving as markdown.
    Supports both toolbar buttons and auto-markdown syntax.
    """

    textChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._read_only = False
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_auto_markdown()

    def _setup_ui(self) -> None:
        """Setup the editor UI with toolbar and text area."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self._setup_toolbar()
        layout.addWidget(self.toolbar)

        # Editor
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.textChanged.connect(self.textChanged.emit)
        layout.addWidget(self.editor)

    def _setup_toolbar(self) -> None:
        """Setup formatting toolbar."""
        # Bold
        self.bold_action = QAction("B", self)
        self.bold_action.setToolTip("Bold (Ctrl+B)")
        self.bold_action.setCheckable(True)
        self.bold_action.triggered.connect(self._toggle_bold)
        bold_btn = QToolButton()
        bold_btn.setDefaultAction(self.bold_action)
        bold_btn.setFont(QFont("", -1, QFont.Weight.Bold))
        self.toolbar.addWidget(bold_btn)

        # Italic
        self.italic_action = QAction("I", self)
        self.italic_action.setToolTip("Italic (Ctrl+I)")
        self.italic_action.setCheckable(True)
        self.italic_action.triggered.connect(self._toggle_italic)
        italic_btn = QToolButton()
        italic_btn.setDefaultAction(self.italic_action)
        italic_font = QFont()
        italic_font.setItalic(True)
        italic_btn.setFont(italic_font)
        self.toolbar.addWidget(italic_btn)

        # Strikethrough
        self.strike_action = QAction("S", self)
        self.strike_action.setToolTip("Strikethrough (Ctrl+Shift+S)")
        self.strike_action.setCheckable(True)
        self.strike_action.triggered.connect(self._toggle_strikethrough)
        strike_btn = QToolButton()
        strike_btn.setDefaultAction(self.strike_action)
        strike_font = QFont()
        strike_font.setStrikeOut(True)
        strike_btn.setFont(strike_font)
        self.toolbar.addWidget(strike_btn)

        self.toolbar.addSeparator()

        # Header dropdown
        header_btn = QToolButton()
        header_btn.setText("H")
        header_btn.setToolTip("Headers")
        header_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header_menu = QMenu(header_btn)
        header_menu.addAction("Heading 1", lambda: self._apply_header(1))
        header_menu.addAction("Heading 2", lambda: self._apply_header(2))
        header_menu.addAction("Heading 3", lambda: self._apply_header(3))
        header_menu.addSeparator()
        header_menu.addAction("Normal", lambda: self._apply_header(0))
        header_btn.setMenu(header_menu)
        self.toolbar.addWidget(header_btn)

        self.toolbar.addSeparator()

        # Bullet list
        bullet_action = QAction("•", self)
        bullet_action.setToolTip("Bullet List (Ctrl+Shift+U)")
        bullet_action.triggered.connect(self._toggle_bullet_list)
        self.toolbar.addAction(bullet_action)

        # Numbered list
        number_action = QAction("1.", self)
        number_action.setToolTip("Numbered List (Ctrl+Shift+O)")
        number_action.triggered.connect(self._toggle_numbered_list)
        self.toolbar.addAction(number_action)

        self.toolbar.addSeparator()

        # Code/monospace
        code_action = QAction("</>", self)
        code_action.setToolTip("Code (Ctrl+`)")
        code_action.triggered.connect(self._toggle_code)
        self.toolbar.addAction(code_action)

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts."""
        # Bold: Ctrl+B
        self.bold_action.setShortcut(QKeySequence("Ctrl+B"))

        # Italic: Ctrl+I
        self.italic_action.setShortcut(QKeySequence("Ctrl+I"))

        # Strikethrough: Ctrl+Shift+S
        self.strike_action.setShortcut(QKeySequence("Ctrl+Shift+S"))

    def _setup_auto_markdown(self) -> None:
        """Setup auto-markdown detection."""
        self.editor.textChanged.connect(self._check_auto_markdown)
        self._last_text = ""

    def _check_auto_markdown(self) -> None:
        """Check for markdown patterns and auto-convert."""
        if self._read_only:
            return

        cursor = self.editor.textCursor()
        block = cursor.block()
        text = block.text()

        # Skip if text hasn't changed in a way that matters
        if text == self._last_text:
            return
        self._last_text = text

        # Check for line-start patterns (triggered by space)
        if text.endswith(" "):
            line_start = text.rstrip()

            # Headers: # ## ###
            if re.match(r"^#{1,3}$", line_start):
                level = len(line_start)
                self._convert_line_to_header(cursor, level, line_start + " ")
                return

            # Bullet list: - or *
            if line_start in ("-", "*"):
                self._convert_line_to_bullet(cursor, line_start + " ")
                return

            # Numbered list: 1. 2. etc
            if re.match(r"^\d+\.$", line_start):
                self._convert_line_to_numbered(cursor, line_start + " ")
                return

            # Blockquote: >
            if line_start == ">":
                self._convert_line_to_blockquote(cursor, line_start + " ")
                return

        # Check for inline patterns
        # Bold: **text**
        bold_match = re.search(r"\*\*([^*]+)\*\*$", text)
        if bold_match:
            self._convert_inline_format(cursor, bold_match, "bold")
            return

        # Italic: *text* (but not **)
        italic_match = re.search(r"(?<!\*)\*([^*]+)\*$", text)
        if italic_match and "**" not in text[-len(italic_match.group(0)) - 2 :]:
            self._convert_inline_format(cursor, italic_match, "italic")
            return

        # Inline code: `text`
        code_match = re.search(r"`([^`]+)`$", text)
        if code_match:
            self._convert_inline_format(cursor, code_match, "code")
            return

    def _convert_line_to_header(self, cursor: QTextCursor, level: int, pattern: str) -> None:
        """Convert current line to a header."""
        # Select and remove the markdown pattern
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            len(pattern),
        )
        cursor.removeSelectedText()

        # Apply header format
        self._apply_header(level)

    def _convert_line_to_bullet(self, cursor: QTextCursor, pattern: str) -> None:
        """Convert current line to bullet list."""
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            len(pattern),
        )
        cursor.removeSelectedText()
        self._toggle_bullet_list()

    def _convert_line_to_numbered(self, cursor: QTextCursor, pattern: str) -> None:
        """Convert current line to numbered list."""
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            len(pattern),
        )
        cursor.removeSelectedText()
        self._toggle_numbered_list()

    def _convert_line_to_blockquote(self, cursor: QTextCursor, pattern: str) -> None:
        """Convert current line to blockquote."""
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            len(pattern),
        )
        cursor.removeSelectedText()

        # Apply blockquote formatting (indent)
        block_format = cursor.blockFormat()
        block_format.setLeftMargin(20)
        cursor.setBlockFormat(block_format)

    def _convert_inline_format(
        self, cursor: QTextCursor, match: re.Match, format_type: str
    ) -> None:
        """Convert inline markdown to formatting."""
        text = match.group(1)
        full_match = match.group(0)

        # Find and select the markdown pattern
        block = cursor.block()
        block_start = block.position()
        match_start = block_start + match.start()

        cursor.setPosition(match_start)
        cursor.setPosition(match_start + len(full_match), QTextCursor.MoveMode.KeepAnchor)

        # Create format
        fmt = QTextCharFormat()
        if format_type == "bold":
            fmt.setFontWeight(QFont.Weight.Bold)
        elif format_type == "italic":
            fmt.setFontItalic(True)
        elif format_type == "code":
            fmt.setFontFamily("monospace")
            fmt.setBackground(Qt.GlobalColor.darkGray)

        # Replace with formatted text
        cursor.removeSelectedText()
        cursor.insertText(text, fmt)

        # Reset format for next text
        cursor.setCharFormat(QTextCharFormat())
        self.editor.setTextCursor(cursor)

    def _toggle_bold(self) -> None:
        """Toggle bold formatting on selection."""
        fmt = QTextCharFormat()
        if self.editor.fontWeight() == QFont.Weight.Bold:
            fmt.setFontWeight(QFont.Weight.Normal)
        else:
            fmt.setFontWeight(QFont.Weight.Bold)
        self._merge_format(fmt)

    def _toggle_italic(self) -> None:
        """Toggle italic formatting on selection."""
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.editor.fontItalic())
        self._merge_format(fmt)

    def _toggle_strikethrough(self) -> None:
        """Toggle strikethrough formatting on selection."""
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.editor.currentCharFormat().fontStrikeOut())
        self._merge_format(fmt)

    def _toggle_code(self) -> None:
        """Toggle code/monospace formatting on selection."""
        fmt = QTextCharFormat()
        current = self.editor.currentCharFormat()
        if current.fontFamily() == "monospace":
            fmt.setFontFamily("")
        else:
            fmt.setFontFamily("monospace")
        self._merge_format(fmt)

    def _apply_header(self, level: int) -> None:
        """Apply header formatting to current block."""
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)

        fmt = QTextCharFormat()
        if level == 0:
            # Normal text
            fmt.setFontWeight(QFont.Weight.Normal)
            fmt.setFontPointSize(12)
        elif level == 1:
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(24)
        elif level == 2:
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(20)
        elif level == 3:
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(16)

        cursor.mergeCharFormat(fmt)
        self.editor.setTextCursor(cursor)

    def _toggle_bullet_list(self) -> None:
        """Toggle bullet list on current block."""
        cursor = self.editor.textCursor()
        current_list = cursor.currentList()

        if current_list and current_list.format().style() == QTextListFormat.Style.ListDisc:
            # Remove from list
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(0)
            cursor.setBlockFormat(block_fmt)
        else:
            # Add to list
            list_fmt = QTextListFormat()
            list_fmt.setStyle(QTextListFormat.Style.ListDisc)
            cursor.createList(list_fmt)

    def _toggle_numbered_list(self) -> None:
        """Toggle numbered list on current block."""
        cursor = self.editor.textCursor()
        current_list = cursor.currentList()

        if current_list and current_list.format().style() == QTextListFormat.Style.ListDecimal:
            # Remove from list
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(0)
            cursor.setBlockFormat(block_fmt)
        else:
            # Add to list
            list_fmt = QTextListFormat()
            list_fmt.setStyle(QTextListFormat.Style.ListDecimal)
            cursor.createList(list_fmt)

    def _merge_format(self, fmt: QTextCharFormat) -> None:
        """Merge format into current selection or cursor position."""
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    # Public API

    def get_markdown(self) -> str:
        """Export content as markdown."""
        html = self.editor.toHtml()
        return html_to_markdown(html)

    def set_markdown(self, text: str) -> None:
        """Load markdown content."""
        # Clear first to ensure no stale content
        self.editor.clear()

        if text and text.strip():
            # Strip any CSS preamble that may have leaked into stored markdown
            # (from bug where QTextEdit CSS wasn't being filtered)
            if text.startswith("p, li {") or text.startswith("p,li{"):
                # Find the end of the CSS block and skip it
                lines = text.split("\n")
                clean_lines = []
                skip = True
                for line in lines:
                    if skip:
                        # Skip lines that look like CSS
                        if "{" in line or "}" in line or line.strip().startswith("li."):
                            continue
                        skip = False
                    if not skip:
                        clean_lines.append(line)
                text = "\n".join(clean_lines).strip()

            if text:
                html = markdown_to_html(text)
                self.editor.setHtml(html)

        self._last_text = ""

    def get_plain_text(self) -> str:
        """Get plain text without formatting."""
        return self.editor.toPlainText()

    def set_plain_text(self, text: str) -> None:
        """Set plain text."""
        self.editor.setPlainText(text)
        self._last_text = ""

    def clear(self) -> None:
        """Clear the editor."""
        self.editor.clear()
        self._last_text = ""

    def set_read_only(self, read_only: bool) -> None:
        """Set read-only mode."""
        self._read_only = read_only
        self.editor.setReadOnly(read_only)
        self.toolbar.setVisible(not read_only)

    def is_read_only(self) -> bool:
        """Check if editor is read-only."""
        return self._read_only

    def set_placeholder_text(self, text: str) -> None:
        """Set placeholder text."""
        self.editor.setPlaceholderText(text)

    def setFocus(self) -> None:
        """Set focus to the editor."""
        self.editor.setFocus()

    def document(self):
        """Get the underlying document."""
        return self.editor.document()
