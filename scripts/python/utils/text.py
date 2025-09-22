import re

_CTRL_RX = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')
# NMS color/format markers look like \u0013#RRGGBB; sometimes repeated inline
_FMT_RX  = re.compile(r'\u0013#[0-9A-Fa-f]{6}')

def strip_control_codes(s):
    """Remove control chars and NMS inline color codes from a string."""
    if not isinstance(s, str):
        return s
    s = _CTRL_RX.sub('', s)
    s = _FMT_RX.sub('', s)
    return s
