# High-DPI and Layout Management in PyQt6

## High-DPI Support

To ensure the application looks crisp on pixel-dense displays (like 4K or Retina), always ensure the following attributes are considered in the main entry point:

```python
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

def main():
    app = QApplication([])
    # PyQt6 usually handles this by default, but for legacy compatibility:
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    ...
```

## Sizing and Scaling Strategies

### 1. Avoid Fixed Sizes
Avoid `setFixedSize()` unless absolutely necessary for small, static icons or buttons. Use `setMinimumSize()` and `setMaximumSize()` instead.

### 2. Use Layouts for Everything
Never use absolute positioning. Use `QVBoxLayout`, `QHBoxLayout`, and `QGridLayout`.

### 3. Size Policies
Set appropriate size policies to control how widgets expand:
- `QSizePolicy.Policy.Expanding`: Widget takes as much space as possible.
- `QSizePolicy.Policy.MinimumExpanding`: Widget takes minimum space but can expand.
- `QSizePolicy.Policy.Fixed`: Widget size does not change.

### 4. Spacing and Margins
High-DPI screens can make standard 1px borders or 5px margins look tiny. Use relative spacing or scale margins based on a base unit.

```python
# Scale a base unit (e.g., 8px) for high-DPI
logical_dpi = app.primaryScreen().logicalDotsPerInch()
scale_factor = logical_dpi / 96.0
margin = int(8 * scale_factor)
```

## Common "Visual Quirks" & Fixes

- **Blurry Text:** Ensure `Qt.ApplicationAttribute.AA_EnableHighDpiScaling` is active (default in Qt6).
- **Tiny Icons:** Use `QIcon` with SVG files or multi-resolution `.ico`/`.icns` files.
- **Overlapping Widgets:** Usually caused by fixed heights/widths. Use `stretch` factors in layouts.
