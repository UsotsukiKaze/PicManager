"""Coalesce snapshot requests without making HTTP workers wait for file I/O."""
import threading
import time


class SnapshotWorker:
    def __init__(self, backup, *, interval=30, debounce=.25):
        self.backup = backup
        self.interval = interval
        self.debounce = debounce
        self.condition = threading.Condition()
        self.pending = False
        self.stopped = False
        self.thread = None

    def request(self):
        with self.condition:
            self.pending = True
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='db_snapshot_writer', daemon=True)
                self.thread.start()
            self.condition.notify()

    def run(self):
        last = float('-inf')
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.stopped)
                if self.stopped:
                    return
                deadline = max(time.monotonic() + self.debounce, last + self.interval)
                while not self.stopped and time.monotonic() < deadline:
                    self.condition.wait(deadline - time.monotonic())
                if self.stopped:
                    return
                self.pending = False
            try:
                success = self.backup()
            except Exception:
                success = False
            last = time.monotonic()
            if not success:
                with self.condition:
                    self.pending = True

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify()
        if self.thread:
            self.thread.join(timeout=5)
