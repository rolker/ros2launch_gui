import re

# ANSI color code mapping to HTML colors
ANSI_COLOR_MAP = {
    '30': '#FFFFFF',  # Black
    '31': '#FF0000',  # Red
    '32': '#00FF00',  # Green
    '33': '#FF7F00',  # Yellow (actually Orange for better readability)
    '34': '#0000FF',  # Blue
    '35': '#FF00FF',  # Magenta
    '36': '#00FFFF',  # Cyan
    '37': '#FFFFFF',  # White (actually Black to see it on white background)
}

# Regular expression to match ANSI escape codes
ansi_color_re = re.compile(r'\033\[([0-9;]*)m')


def ansi_to_html(text):
    matches = ansi_color_re.match(text)
    if not matches:
        return text
    codes = matches.group(1).split(';')
    # remove the ANSI escape codes from the text
    text = ansi_color_re.sub('', text)
    if not codes:
        return text

    modifier = None
    color_code = None
    # reset case
    if codes[0] == '0':
        return text
    # color + modifier
    if len(codes) > 1:
        modifier = codes[0]
        color_code = ANSI_COLOR_MAP.get(codes[1])
    # only color code present
    else:
        color_code = ANSI_COLOR_MAP.get(codes[0])

    html_start = f'<span style="color: {color_code}">'
    html_end = '</span>'
    if modifier == '1':
        html_text = f'{html_start}<b>{text}</b>{html_end}'
    elif modifier == '3':
        html_text = f'{html_start}<i>{text}</i>{html_end}'
    elif modifier == '4':
        html_text = f'{html_start}<u>{text}</u>{html_end}'
    else:
        html_text = f'{html_start}{text}{html_end}'
    return html_text
