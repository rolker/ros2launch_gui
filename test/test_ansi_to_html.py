#import pytest
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
