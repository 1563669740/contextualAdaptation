#
# Holdout tests for task python-babel__babel-1120
#
# Authored independently under the paper's Section V-G rules:
#   * the author did not run any experimental session
#   * the author saw the issue, the base commit and the gold patch only
#   * the author never saw a candidate patch or a delegation/context label
#
# Coverage rationale -- why these are not duplicates of the benchmark test:
#
#   The benchmark test asserts ONE enclosed location at width=1 with an integer
#   line number.  The tests below pin down what it never exercises: two spaced
#   filenames on the same message, the exact rendered text for a different
#   filename and line number, the interaction with `width=None`/large widths,
#   and the wrapping primitive's obligation not to break a filename apart.
#
#   Every assertion was validated against the real behaviour of BOTH revisions.
#   This matters more than it sounds: at width=24 the PO layer behaves
#   identically before and after the fix, so a test written at that width would
#   have "passed" while measuring nothing.  The discriminating width at the PO
#   layer is 1 (and 0/None), which is exactly why the benchmark uses it.  What
#   the benchmark does not do is combine it with several locations or with the
#   wrapper directly -- that is the gap these tests occupy.
#
import io

from babel.messages import pofile
from babel.messages.catalog import Catalog
from babel.util import TextWrapper

# Unicode FIRST STRONG ISOLATE / POP DIRECTIONAL ISOLATE: the markers babel uses
# to keep a filename containing spaces indivisible.
FSI = "\u2068"
PDI = "\u2069"

NARROW = 1          # width at which the defect is observable in PO output
ROOMY = 76          # width at which it is not


def _location_lines(locations, width):
    """Write a one-message catalog and return its '#:' comment lines."""
    catalog = Catalog()
    catalog.add("foo", locations=locations)
    buf = io.BytesIO()
    pofile.write_po(buf, catalog, omit_header=True, include_lineno=True,
                    width=width)
    return [line for line in buf.getvalue().decode("utf-8").splitlines()
            if line.startswith("#:")]


def _whole(line):
    """A line is whole when it does not split a filename, i.e. the isolate
    markers are balanced.  A split filename leaves a dangling FSI or PDI."""
    return line.count(FSI) == line.count(PDI)


def test_hd_two_enclosed_locations_at_width_one():
    """Two spaced filenames on one message must both stay intact at width=1.

    The benchmark covers a single location at width=1.  With two, the naive
    wrapper emits one comment line per character for each of them instead of one
    line per location.
    """
    lines = _location_lines([(FSI + "x y.py" + PDI, 1),
                             (FSI + "p q.py" + PDI, 2)], width=NARROW)
    assert "#: " + FSI + "p q.py" + PDI + ":2" in lines, lines
    assert "#: " + FSI + "x y.py" + PDI + ":1" in lines, lines
    assert len(lines) == 2, lines


def test_hd_three_enclosed_locations_at_width_one():
    """Three locations, mixed filenames, all intact and all accounted for."""
    lines = _location_lines([(FSI + "a b.py" + PDI, 3),
                             (FSI + "name with spaces.py" + PDI, 11),
                             ("plain.py", 5)], width=NARROW)
    assert "#: " + FSI + "a b.py" + PDI + ":3" in lines, lines
    assert "#: " + FSI + "name with spaces.py" + PDI + ":11" in lines, lines
    assert "#: plain.py:5" in lines, lines
    assert len(lines) == 3, lines


def test_hd_single_enclosed_location_text_is_exact():
    """Byte-exact rendered comment for a filename and line number the
    benchmark never uses."""
    lines = _location_lines([(FSI + "only file.py" + PDI, 42)], width=NARROW)
    assert lines == ["#: " + FSI + "only file.py" + PDI + ":42"]


def test_hd_roomy_width_still_keeps_locations_intact():
    """At a comfortable width nothing may be split or reordered per location.

    Both revisions agree here, so this test alone would not detect the defect;
    it is included to pin the behaviour that must not regress once the narrow
    case is fixed.
    """
    lines = _location_lines([(FSI + "x y.py" + PDI, 1),
                             (FSI + "p q.py" + PDI, 2)], width=ROOMY)
    joined = " ".join(lines)
    assert FSI + "x y.py" + PDI + ":1" in joined
    assert FSI + "p q.py" + PDI + ":2" in joined
    assert all(_whole(line) for line in lines), lines


def test_hd_wrapper_never_splits_inside_an_enclosed_filename():
    """No wrapped line may break a filename apart.

    At width=24 the naive wrapper emits the two spaced filenames across four
    fragments, leaving the isolate markers unbalanced within a line; the fixed
    wrapper keeps each name whole.
    """
    text = (FSI + "one two.py" + PDI + ":1 "
            + FSI + "three four.py" + PDI + ":2")
    out = TextWrapper(width=24).wrap(text)
    assert out, "wrapper produced no output"
    assert all(_whole(line) for line in out), out
    assert all(FSI in line and PDI in line for line in out), out
