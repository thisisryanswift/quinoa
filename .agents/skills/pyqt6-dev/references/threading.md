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
Never call `QThread.terminate()`. It leaves objects and locks in an undefined state and can corrupt the audio pipeline or database. Instead, use cooperative cancellation and wait for `run()` to return.

```python
def stop_worker(worker: MyWorker) -> None:
    worker.cancel()                 # set _is_cancelled + requestInterruption()
    if not worker.wait(msecs=5000): # wait up to 5 s
        logger.warning("Worker did not finish in time; it will be cleaned up when its terminal signal fires")
```

Inside `run()`, poll a cancellation flag and/or `isInterruptionRequested()` at safe boundaries:

```python
def run(self):
    try:
        for item in self.data:
            if self._is_cancelled or self.isInterruptionRequested():
                return
            self.process(item)
    except Exception as e:
        self.error.emit(str(e))
    finally:
        # Emit a terminal signal (e.g. `done`) so the manager can delete the
        # worker only after it has truly stopped.
        self.done.emit()
```

Quinoa workers combine a private `_is_cancelled` flag, a `threading.Event` for blocking I/O (such as ffmpeg or network calls), and `requestInterruption()` for the Qt event loop. See `quinoa/ui/transcribe_worker.py` and `quinoa/transcription/manager.py` for the canonical project pattern.
