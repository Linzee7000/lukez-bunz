"""Undo the Garbage route-map PDFs' broken font export.

Those PDFs come out of Publisher with a font whose ToUnicode table is wrong, so every character
extracts as an unrelated codepoint - 'Monday Run 201 Garbage' comes out as 'DŽŶĚĂǇZƵŶϮϬϭ'ĂƌďĂŐĞ'.
It looks like gibberish, which is why this was originally worked around by matching each page's
route geometry against every candidate run instead (see identify_garbage.py).

It isn't gibberish though: the substitution is *consistent* - the same character always maps to the
same wrong codepoint - and it's the same table in all five day files. So it can simply be undone,
which reads the run number straight off the page and is both exact and far better covered than
guessing from geometry.

The table below was built from known text on the pages ('Monday', 'Run', 'Garbage', 'Schools',
'Drivers Notes', 'Reverse In', 'Drive In, Reverse Out', 'Start L1', 'Bin Count Est.', 'Gate Code #',
'Map 1/3', 'Load 1') and then extended by decoding street names and checking them against the
street names in the master property list - see check_font_table() and tests in this file's __main__.
"""
import re

# wrong codepoint -> real character
TABLE = {
    0x0003: ' ',
    # Uppercase. Note these run through ordinary ASCII codepoints too ('d' means 'T', 'h' means
    # 'U'), which is why the gibberish has stray real letters sprinkled through it and why an
    # undecoded page can look *almost* readable - 'dƵĞƐĚĂǇ' is 'Tuesday'.
    0x0004: 'A', 0x0011: 'B', 0x0012: 'C', 0x0018: 'D', 0x001C: 'E', 0x0026: 'F', 0x0027: 'G',
    0x002C: 'H', 0x002F: 'I', 0x003C: 'K', 0x003E: 'L', 0x0044: 'M', 0x0045: 'N',
    0x004B: 'O', 0x0057: 'P', 0x005A: 'R', 0x005E: 'S', 0x0064: 'T', 0x0068: 'U',
    0x0073: 'V', 0x0074: 'W', 0x007A: 'Y',
    # lowercase, including the f-ligatures the font keeps as single glyphs
    0x0102: 'a', 0x010F: 'b', 0x0110: 'c', 0x011A: 'd', 0x011E: 'e',
    0x0128: 'f', 0x012B: 'ff', 0x012E: 'fi', 0x014C: 'ft', 0x0150: 'g', 0x015A: 'h', 0x015D: 'i',
    0x016C: 'k', 0x016F: 'l', 0x0175: 'm', 0x0176: 'n', 0x017D: 'o', 0x0189: 'p',
    0x018C: 'r', 0x0190: 's', 0x019A: 't', 0x019F: 'ti', 0x01B5: 'u', 0x01C0: 'v',
    0x01C1: 'w', 0x01C6: 'x', 0x01C7: 'y', 0x01CC: 'z',
    # punctuation
    0x0355: ',', 0x0358: '.', 0x0357: ':', 0x036C: '/', 0x037F: ')', 0x03B7: '#',
}
# digits are linear, unlike everything else
for _d in range(10):
    TABLE[0x03EC + _d] = chr(ord('0') + _d)


def decode(s):
    """Decode extracted text. Characters not in the table are left as-is."""
    return ''.join(TABLE.get(ord(ch), ch) for ch in s)


def unknown_chars(s):
    """Codepoints in s that the table doesn't cover (ignoring ordinary ASCII/whitespace)."""
    out = {}
    for ch in s:
        o = ord(ch)
        if o in TABLE or ch.isspace() or 32 <= o < 127:
            continue
        out[ch] = out.get(ch, 0) + 1
    return out


TITLE_RE = re.compile(
    r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*Run\s*(\d+)\s*Garbage', re.I)


def read_title(page_text):
    """-> (day, run) read off a decoded page, or None if the page has no run title."""
    m = TITLE_RE.search(decode(page_text))
    return (m.group(1).title(), m.group(2)) if m else None


def page_texts(pdf):
    """Extract every page's raw (still-encoded) text in one pdftotext pass -> {page_no: text}.

    `pdf` is a filename inside lib.DL, the same as page_routes/page_count take. One pass for the
    whole file matters here: these PDFs are 130-200MB each, so running pdftotext once per page
    would re-parse the whole thing dozens of times.
    """
    import os, subprocess
    from lib import DL
    path = pdf if os.path.isabs(pdf) else os.path.join(DL, pdf)
    r = subprocess.run(['pdftotext', path, '-'], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'pdftotext failed on {path}: {r.stderr.strip()[:200]}')
    return {i: t for i, t in enumerate(r.stdout.split('\f'), 1)}
