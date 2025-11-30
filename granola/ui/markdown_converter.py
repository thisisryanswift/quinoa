"""Markdown ↔ HTML conversion utilities for the WYSIWYG editor."""

import re

import markdown
import markdownify


def markdown_to_html(md_text: str) -> str:
    """Convert markdown to HTML for display in QTextEdit.

    Args:
        md_text: Markdown formatted text

    Returns:
        HTML string suitable for QTextEdit.setHtml()
    """
    if not md_text:
        return ""

    # Convert markdown to HTML with useful extensions
    html = markdown.markdown(
        md_text,
        extensions=[
            "fenced_code",  # ```code blocks```
            "tables",  # | table | support |
            "nl2br",  # Convert newlines to <br>
        ],
    )

    return html


def html_to_markdown(html: str) -> str:
    """Convert HTML back to markdown for storage.

    Args:
        html: HTML from QTextEdit.toHtml()

    Returns:
        Clean markdown text
    """
    if not html:
        return ""

    # QTextEdit.toHtml() returns a full HTML document with CSS preamble.
    # Extract just the body content to avoid CSS leaking into markdown.
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    if body_match:
        html = body_match.group(1)

    # Also strip any remaining style tags and their content
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Convert HTML to markdown
    md = markdownify.markdownify(
        html,
        heading_style="ATX",  # Use # style headers
        bullets="-",  # Use - for unordered lists
        strip=["script", "style"],  # Remove dangerous tags
    )

    # Clean up extra whitespace that markdownify sometimes produces
    lines = md.split("\n")
    cleaned_lines = []
    prev_empty = False

    for line in lines:
        is_empty = not line.strip()
        # Don't allow more than one consecutive empty line
        if is_empty and prev_empty:
            continue
        cleaned_lines.append(line.rstrip())
        prev_empty = is_empty

    return "\n".join(cleaned_lines).strip()
