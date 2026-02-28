---
name: pyqt6-dev
description: Expert guidance for developing PyQt6 applications. Use when implementing UI components, managing background workers with QThread, handling signals/slots, or troubleshooting high-DPI sizing and layout issues.
---

# PyQt6 Development Guide

This skill provides expert patterns for building robust, responsive, and high-DPI aware PyQt6 applications. It's designed to help Gemini CLI build maintainable UI code and handle complex background operations.

## Core Workflows

### 1. Multi-threaded Workers (QThread)

Use this workflow to implement background tasks like file processing, API calls, or database operations without freezing the GUI.

1.  **Define Worker:** Create a subclass of `QThread`.
2.  **Define Signals:** Use `pyqtSignal` for results (`finished`), progress (`progress`), or errors (`error`).
3.  **Implement `run()`:** Always wrap logic in a `try-except` block.
4.  **Connect Signals:** In the main thread, connect signals to UI slots *before* starting.

See [threading.md](references/threading.md) for detailed implementation patterns and safety rules.

### 2. High-DPI & Responsive Layouts

Use this workflow to ensure the UI looks correct on all display resolutions, especially pixel-dense screens.

1.  **Use Layouts:** Never use absolute positioning or fixed pixel sizes (`setFixedSize()`).
2.  **Stretch Factors:** Use `addStretch()` or layout stretch factors to control how space is distributed.
3.  **Size Policies:** Use `QSizePolicy` (e.g., `Expanding` vs. `Minimum`) to define widget behavior during window resizing.

See [layouts.md](references/layouts.md) for scaling strategies and fixes for common "visual quirks."

## Common Pitfalls & Best Practices

### Signal/Slot Cleanliness
- **Disconnect:** Use `sender().disconnect()` or track connections to avoid duplicate signal handling if a widget is reused.
- **Thread Affinity:** Ensure that long-lived objects (`QTimer`, `QNetworkAccessManager`) are created in the thread where they will be used.

### Widget Lifecycle
- **Parenting:** Always set a parent for widgets (`QWidget(parent)`) to ensure automatic memory management by Qt's parent-child system.
- **Garbage Collection:** Be careful with local variables for widgets; if they go out of scope without a parent, they will be deleted.

## Quick References

- **Multithreading Pattern:** See `references/threading.md`
- **Layouts & Sizing Guide:** See `references/layouts.md`
