# Multithreading with QThread in PyQt6

## Subclassing QThread (Recommended for Simple Workers)

This is the pattern primarily used in this project. Define a class that inherits from `QThread` and override its `run()` method.

```python
from PyQt6.QtCore import QThread, pyqtSignal

class MyWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def run(self):
        try:
            # Perform long-running task
            result = self.do_work(self.data)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def do_work(self, data):
        # Implementation...
        pass
```

### Key Rules for Threads:
1. **NEVER modify UI widgets from a non-GUI thread.** Always use `pyqtSignal` to communicate results or progress back to the main thread.
2. **Handle Exceptions:** Always wrap the `run()` method in a `try-except` block and emit an `error` signal to avoid crashing the whole application.
3. **Avoid QThread Subclassing for State?** (Alternative: `QObject.moveToThread`). While the current project uses subclassing, `moveToThread` is sometimes safer for long-running objects that need to handle their own signals/slots.

## Starting and Stopping Workers

### Safe Start
```python
worker = MyWorker(data)
worker.finished.connect(handle_result)
worker.error.connect(handle_error)
worker.start()
```

### Safe Stop
Wait for threads to finish before closing the application or destroying widgets.
```python
if worker.isRunning():
    worker.terminate() # Only as a last resort
    worker.wait()
```
Prefer cooperative cancellation (using a flag like `self._is_cancelled`) over `terminate()`.
