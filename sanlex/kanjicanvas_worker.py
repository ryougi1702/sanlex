"""Isolate Qt JavaScript execution so recognition never holds the UI's GIL."""
import json
import multiprocessing
import time

from .db import resource_path
from .handwriting import normalize


def serve_kanjicanvas(connection):
    from PySide6.QtCore import QCoreApplication
    from .kanjicanvas import KanjiCanvasRecognizer
    application = QCoreApplication([])
    try:
        recognizer = KanjiCanvasRecognizer()
        connection.send(('ready', None))
        while True:
            strokes, limit = connection.recv()
            connection.send(('result', recognizer.recognize(strokes, limit=limit)))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as error:
        connection.send(('error', str(error)))
    finally:
        connection.close()


class KanjiCanvasProcess:
    def __init__(self, *, cancelled=lambda: False, target=serve_kanjicanvas):
        manifest = json.loads(resource_path('assets/kanjicanvas/manifest.json').read_text(encoding='utf-8'))
        self.chars = set(manifest['character_set'])
        self.target = target
        self.process, self.connection = None, None
        self.start(cancelled)

    def start(self, cancelled):
        if cancelled():
            return False
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        self.process = context.Process(target=self.target, args=(child,), daemon=True)
        self.connection = parent
        try:
            self.process.start()
            child.close()
            response = self.receive(cancelled)
            return response is not None and response[0] == 'ready'
        except Exception:
            self.close()
            raise

    def receive(self, cancelled):
        deadline = time.monotonic() + 20
        while not cancelled():
            if self.connection.poll(.05):
                try:
                    response = self.connection.recv()
                except EOFError as error:
                    raise RuntimeError('KanjiCanvas worker exited unexpectedly') from error
                if response[0] == 'error':
                    raise RuntimeError(response[1])
                return response
            if not self.process.is_alive():
                raise RuntimeError('KanjiCanvas worker exited unexpectedly')
            if time.monotonic() > deadline:
                raise RuntimeError('KanjiCanvas recognition timed out')
        self.close()
        return None

    def recognize(self, strokes, mode='ja', limit=24, cancelled=lambda: False):
        if mode != 'ja':
            raise ValueError('KanjiCanvas supports Japanese mode')
        if cancelled() or limit <= 0 or not normalize(strokes):
            return []
        try:
            if self.process is None and not self.start(cancelled):
                return []
            self.connection.send((strokes, limit))
            response = self.receive(cancelled)
            return response[1] if response else []
        except Exception:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None:
            if self.process.pid is not None:
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=3)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
            self.process.close()
            self.process = None
