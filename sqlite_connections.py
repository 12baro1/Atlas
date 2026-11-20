"""Thread-owned SQLite connections for long-running Atlas stores."""
import sqlite3
import threading


class ThreadConnections:
    def __init__(self):
        self._local = threading.local()
        self._owners = {}
        self._lock = threading.Lock()
        self._closed = False

    def get(self, connect):
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        with self._lock:
            if self._closed:
                raise sqlite3.ProgrammingError("Store is closed")
            # Telegram symbol analyses use a new thread for each request.
            # Only retire connections whose owner has completely exited.
            for thread in list(self._owners):
                if not thread.is_alive():
                    self._owners.pop(thread).close()
            connection = connect()
            self._owners[threading.current_thread()] = connection
            self._local.connection = connection
            return connection

    def close(self):
        with self._lock:
            self._closed = True
            for connection in self._owners.values():
                connection.close()
            self._owners.clear()
            self._local = threading.local()
