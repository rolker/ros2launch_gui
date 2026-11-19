from ros2launch_gui.launcher.protocol import encode
from ros2launch_gui.launcher.protocol import LineAssembler
from ros2launch_gui.launcher.protocol import LineDecoder
from ros2launch_gui.launcher.protocol import to_text


def test_line_assembler_joins_chunks_and_utf8():
    assembler = LineAssembler()
    assert assembler.feed(b'part-one ') == ''
    assert assembler.feed(b'\xc3') == ''
    assert assembler.feed(b'\xa9 part-two\nnext') == 'part-one é part-two\n'
    assert assembler.feed(b' line\n\nlast') == 'next line\n\n'
    assert assembler.flush() == 'last'
    assert assembler.flush() == ''


def test_line_assembler_flushes_overlong_partial_line():
    assembler = LineAssembler(max_partial=10)
    assert assembler.feed(b'0123456789abc') == '0123456789abc'
    assert assembler.flush() == ''


def test_line_assembler_invalid_bytes_replaced():
    assembler = LineAssembler()
    assert assembler.feed(b'bad:\xff\n') == 'bad:�\n'


def test_round_trip():
    message = {'type': 'process_io', 'name': 'talker-1', 'text': 'hello\nworld'}
    data = encode(message)
    assert data.endswith(b'\n')
    assert data.count(b'\n') == 1
    assert LineDecoder().feed(data) == [message]


def test_split_across_reads():
    decoder = LineDecoder()
    assert decoder.feed(b'{"type": "sta') == []
    assert decoder.feed(b'rted"}\n') == [{'type': 'started'}]


def test_multiple_lines_one_read():
    decoder = LineDecoder()
    data = encode({'type': 'started'}) + b'\n' + encode({'type': 'launch_exited'})
    assert decoder.feed(data) == [{'type': 'started'}, {'type': 'launch_exited'}]


def test_garbage_line_is_error():
    messages = LineDecoder().feed(b'not json\n')
    assert len(messages) == 1
    assert messages[0]['type'] == 'error'
    assert 'not json' in messages[0]['message']


def test_to_text_non_utf8():
    assert to_text(b'\xff') == '�'
    assert to_text('already text') == 'already text'
