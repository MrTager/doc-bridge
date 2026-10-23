import csv
import io
import random

import pytest

from doc_bridge.cli import ConversionError, csv_to_md, md_to_csv


def records(text, delimiter=","):
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def test_round_trip_special_cells():
    rows = [["姓名", "编号", "说明", "空值"], ["小明", "00123", "a,b|c\\d\r\n下一行\t", ""],
            ["  spaced  ", "=SUM(A1)", "&amp; &#10; <br> `*_[x]~", "   "]]
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    assert records(md_to_csv(csv_to_md(buffer.getvalue()))) == rows


def test_delimiter_and_empty_header():
    text = ';label\n001;"a;b"\n'
    assert records(md_to_csv(csv_to_md(text, ";"), ";"), ";") == records(text, ";")


@pytest.mark.parametrize("text", ["", "\n", "a,b\nx\n", "a\n\n", 'a\n"unfinished'])
def test_reject_invalid_csv(text):
    with pytest.raises(ConversionError):
        csv_to_md(text)


def test_multiple_tables_and_fences():
    first = csv_to_md("a\n1\n")
    second = csv_to_md("b\n2\n")
    text = "```md\n" + first + "```\n\n" + first + "\nprose\n" + second
    with pytest.raises(ConversionError, match="select"):
        md_to_csv(text)
    assert records(md_to_csv(text, table=2)) == [["b"], ["2"]]


@pytest.mark.parametrize("text", ["hello", "| a | b |\n| --- |\n", "| a |\n| --- |\n| x | y |\n"])
def test_reject_unsupported_markdown(text):
    with pytest.raises(ConversionError):
        md_to_csv(text)


def test_html_break_and_escaped_pipe():
    assert records(md_to_csv("| x |\n| --- |\n| a\\|b<br>c |\n")) == [["x"], ["a|b\nc"]]


def test_header_only():
    assert records(md_to_csv(csv_to_md("a,b\n"))) == [["a", "b"]]


def test_randomized_cell_round_trips():
    rng = random.Random(42)
    alphabet = "ab中文012 \t\r\n&<>|\\`*_[]~;,\""
    rows = [["c1", "c2", "c3"]] + [
        ["".join(rng.choice(alphabet) for _ in range(rng.randrange(40))) for _ in range(3)]
        for _ in range(200)
    ]
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    assert records(md_to_csv(csv_to_md(buffer.getvalue()))) == rows
