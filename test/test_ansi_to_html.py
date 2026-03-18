from ros2launch_gui.ansi import ansi_to_html

def test_plain_text_to_html():
    input = "my text"
    assert ansi_to_html(input) == input

def test_info_text_to_html():
    input = "\033[0m[INFO] my text\033[0m"
    expected = '[INFO] my text'
    assert ansi_to_html(input) == expected

def test_colored_text_to_html():
    input = "\033[31mmy text\033[0m"
    expected = '<span style="color: #FF0000">my text</span>'
    assert ansi_to_html(input) == expected

def test_bold_colored_text_to_html():
    input = "\033[1;32mmy text\033[0m"
    expected = '<span style="color: #00FF00"><b>my text</b></span>'
    assert ansi_to_html(input) == expected

def test_underlined_colored_text_to_html():
    input = "\033[4;34mmy text\033[0m"
    expected = '<span style="color: #0000FF"><u>my text</u></span>'
    assert ansi_to_html(input) == expected

def test_italic_colored_text_to_html():
    input = "\033[3;34mmy text\033[0m"
    expected = '<span style="color: #0000FF"><i>my text</i></span>'
    assert ansi_to_html(input) == expected

def test_multi_segment_line():
    """Multiple color regions on one line (typical ROS 2 output)."""
    input = "\033[32m[INFO]\033[0m \033[36m[node]\033[0m: msg"
    expected = (
        '<span style="color: #00FF00">[INFO]</span>'
        ' '
        '<span style="color: #00FFFF">[node]</span>'
        ': msg'
    )
    assert ansi_to_html(input) == expected

def test_mid_line_color_change_no_reset():
    """Color changes mid-line without reset in between."""
    input = "\033[31mred\033[32mgreen\033[0m"
    expected = (
        '<span style="color: #FF0000">red</span>'
        '<span style="color: #00FF00">green</span>'
    )
    assert ansi_to_html(input) == expected

def test_only_reset_codes():
    """Reset codes around plain text produce unstyled output."""
    input = "\033[0mplain text\033[0m"
    expected = 'plain text'
    assert ansi_to_html(input) == expected

def test_unknown_256_color_code():
    """Unknown 256-color code is stripped; text rendered without styling."""
    input = "\033[38;5;196mtext\033[0m"
    expected = 'text'
    assert ansi_to_html(input) == expected

def test_consecutive_resets():
    """Multiple consecutive resets before text."""
    input = "\033[0m\033[0mtext"
    expected = 'text'
    assert ansi_to_html(input) == expected

def test_modifier_with_multi_segment():
    """Modifiers combined with colors across multiple segments."""
    input = "\033[1;31mbold red\033[0m normal \033[4;34munderline blue\033[0m"
    expected = (
        '<span style="color: #FF0000"><b>bold red</b></span>'
        ' normal '
        '<span style="color: #0000FF"><u>underline blue</u></span>'
    )
    assert ansi_to_html(input) == expected
