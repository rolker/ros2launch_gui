"""
JSON-lines protocol between the launcher window and a launch runner process.

Runner to window (events), field ``type``: ``started``, ``process_started``,
``process_io``, ``process_exited``, ``state_transition``, ``launch_exited``, ``error``.

Window to runner (commands), field ``type``: ``shutdown``, ``stop_process``, ``lifecycle``.
"""

import codecs
import json
from typing import List
from typing import Union


def encode(message: dict) -> bytes:
    """Encode one message as a single newline-terminated JSON line."""
    return json.dumps(message).encode('utf-8') + b'\n'


def to_text(data: Union[bytes, str]) -> str:
    """Return data as text, replacing bytes that are not valid UTF-8."""
    if isinstance(data, bytes):
        return data.decode('utf-8', errors='replace')
    return data


class LineAssembler:
    """
    Turn raw output chunks into complete lines of text.

    Process output arrives in arbitrary pipe chunks that can end mid-line or even inside a
    multi-byte UTF-8 character; decoding and splitting each chunk alone breaks both.
    """

    def __init__(self, max_partial: int = 65536):
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._partial = ''
        self._max_partial = max_partial

    def feed(self, data: bytes) -> str:
        """Return the complete lines (with newlines) that data finishes, possibly ''."""
        text = self._partial + self._decoder.decode(data)
        end = text.rfind('\n') + 1
        complete, self._partial = text[:end], text[end:]
        if len(self._partial) > self._max_partial:
            complete, self._partial = complete + self._partial, ''
        return complete

    def flush(self) -> str:
        """Return whatever is left, complete line or not."""
        text = self._partial + self._decoder.decode(b'', final=True)
        self._partial = ''
        return text


class LineDecoder:
    """Decode a byte stream of JSON lines that may arrive in arbitrary chunks."""

    def __init__(self):
        self._buffer = b''

    def feed(self, data: bytes) -> List[dict]:
        """Add data and return every complete message it finishes."""
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b'\n')
        messages = []
        for line in lines:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                message = None
            if not isinstance(message, dict):
                message = {'type': 'error', 'message': 'Invalid protocol line: ' + to_text(line)}
            messages.append(message)
        return messages
