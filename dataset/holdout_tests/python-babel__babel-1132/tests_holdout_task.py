#
# Holdout tests for task python-babel__babel-1132
#
# Authored independently under the paper's Section V-G rules:
#   * the author did not run any experimental session
#   * the author saw the issue, the base commit and the gold patch only
#   * the author never saw a candidate patch or a delegation/context label
#
# Coverage rationale -- why these are not duplicates of the benchmark test:
#
#   The benchmark asserts four specific PO documents round-trip.  These tests
#   pin the *rule* those four cases are instances of: an obsolete entry must be
#   keyed by message id AND context, exactly like a live entry.  So the tests
#   count entries rather than compare fixed documents, and they use documents
#   the benchmark never shows, which means they fail for the right reason at
#   base_commit rather than for a cosmetic one.
#
from io import BytesIO

from babel.messages import pofile

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def _read(text):
    return pofile.read_po(BytesIO(text.encode("utf-8")))


def _obsolete(text):
    return _read(text).obsolete


def test_hd_two_obsolete_contexts_are_kept_separately():
    """Two obsolete entries sharing a msgid but differing in msgctxt must both
    survive.  Keying obsolete entries by msgid alone silently drops one."""
    doc = HEADER + (
        "#~ msgctxt \"alpha\"\n"
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"one\"\n"
        "\n"
        "#~ msgctxt \"beta\"\n"
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"two\"\n"
    )
    ob = _obsolete(doc)
    assert len(ob) == 2, f"expected 2 obsolete entries, got {len(ob)}: {list(ob)}"


def test_hd_obsolete_without_context_is_distinct_from_obsolete_with_context():
    """A context-free obsolete entry and a contextualised one must not merge."""
    doc = HEADER + (
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"plain\"\n"
        "\n"
        "#~ msgctxt \"ctx\"\n"
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"contextual\"\n"
    )
    ob = _obsolete(doc)
    assert len(ob) == 2, f"expected 2 obsolete entries, got {len(ob)}: {list(ob)}"


def test_hd_obsolete_context_roundtrips():
    """Reading and re-writing must preserve both contextualised obsolete
    entries -- this is the behaviour the issue is about."""
    doc = HEADER + (
        "#~ msgctxt \"alpha\"\n"
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"one\"\n"
        "\n"
        "#~ msgctxt \"beta\"\n"
        "#~ msgid \"shared\"\n"
        "#~ msgstr \"two\"\n"
    )
    catalog = _read(doc)
    buf = BytesIO()
    pofile.write_po(buf, catalog, omit_header=True)
    again = _obsolete(buf.getvalue().decode("utf-8"))
    assert len(again) == 2, f"roundtrip lost an entry: {list(again)}"
    for key, msg in again.items():
        if isinstance(key, tuple):
            assert key[1] in ("alpha", "beta"), key
