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


def _parse_codes(codes):
    """Parse ANSI code list into (modifier, color) tuple.

    Returns (modifier_tag, color_hex) where modifier_tag is 'b', 'i', 'u',
    or None, and color_hex is an HTML color string or None.
    """
    modifier = None
    color = None

    for code in codes:
        if code == '1':
            modifier = 'b'
        elif code == '3':
            modifier = 'i'
        elif code == '4':
            modifier = 'u'
        elif code in ANSI_COLOR_MAP:
            color = ANSI_COLOR_MAP[code]

    return modifier, color


def ansi_to_html(text):
    """Convert ANSI color codes in text to HTML spans.

    Handles multiple color regions per line, mid-line color changes,
    reset codes, and modifier+color combinations.
    """
    parts = ansi_color_re.split(text)  # [text, codes, text, codes, ...]
    if len(parts) == 1:
        return text  # no ANSI codes — fast path

    result = []
    in_span = False
    pending_modifier = None

    for i, part in enumerate(parts):
        if i % 2 == 1:
            # ANSI code group (captured group from split)
            if in_span:
                result.append('</span>')
                in_span = False
                pending_modifier = None

            codes = part.split(';')
            if codes == ['0'] or codes == ['']:
                # Reset or empty — just close the span (already done above)
                continue

            modifier, color = _parse_codes(codes)
            if color:
                result.append(f'<span style="color: {color}">')
                in_span = True
                pending_modifier = modifier
            # If no recognized color, skip (gracefully strip unknown codes)
        else:
            # Text segment
            if part:
                if pending_modifier and in_span:
                    result.append(
                        f'<{pending_modifier}>{part}</{pending_modifier}>'
                    )
                else:
                    result.append(part)
                pending_modifier = None

    if in_span:
        result.append('</span>')

    return ''.join(result)
