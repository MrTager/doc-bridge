"""Standalone, standard-library CLI; Pandoc is needed only for Word."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class ConversionError(ValueError):
    """A user-facing conversion or validation error."""


def find_pandoc() -> str | None:
    # An installed standalone skill may carry a platform-local backend here.
    bundled = Path(__file__).resolve().parent.parent / "bin" / ("pandoc.exe" if os.name == "nt" else "pandoc")
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    binary = shutil.which("pandoc")
    if binary:
        return binary
    try:
        import pypandoc

        return pypandoc.get_pandoc_path()
    except (ImportError, OSError):
        return None


def encode_cell(value: str) -> str:
    # Encode characters that change pipe-table structure or inline formatting.
    specials = set("&<>|\\`*_[]~")
    encoded = "".join(
        f"&#{ord(char)};" if char in specials or char in "\r\n\t" else char
        for char in value
    )
    leading = len(encoded) - len(encoded.lstrip(" "))
    trailing = len(encoded) - len(encoded.rstrip(" "))
    if leading == len(encoded):
        return "&#32;" * leading
    end = len(encoded) - trailing if trailing else len(encoded)
    return "&#32;" * leading + encoded[leading:end] + "&#32;" * trailing


def csv_to_md(text: str, delimiter: str = ",") -> str:
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise ConversionError(f"Invalid CSV: {exc}") from exc
    if not rows or not rows[0]:
        raise ConversionError("CSV must contain a nonempty header row.")
    width = len(rows[0])
    for number, row in enumerate(rows, 1):
        if len(row) != width:
            raise ConversionError(f"CSV row {number} has {len(row)} columns; expected {width}.")
    lines = ["| " + " | ".join(map(encode_cell, row)) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines) + "\n"


def split_row(line: str) -> list[str]:
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|")):
        raise ConversionError("Tables must use leading and trailing pipes on every row.")
    cells = re.split(r"(?<!\\)\|", line[1:-1])
    return [cell.strip() for cell in cells]


def parse_tables(text: str) -> list[list[list[str]]]:
    tables = []
    lines = text.splitlines()
    fenced = False
    fence_char = ""
    fence_length = 0
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)
            if not fenced:
                fenced, fence_char, fence_length = True, marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length and not stripped[len(marker):].strip():
                fenced = False
            index += 1
            continue
        if fenced or index + 1 >= len(lines) or not stripped.startswith("|"):
            index += 1
            continue
        if not lines[index + 1].strip().startswith("|"):
            index += 1
            continue
        separators = split_row(lines[index + 1])
        if not separators or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators):
            index += 1
            continue
        rows = [split_row(lines[index])]
        if len(rows[0]) != len(separators):
            raise ConversionError("Table header and separator have different column counts.")
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            row = split_row(lines[index])
            if len(row) != len(separators):
                raise ConversionError(f"Markdown row {index + 1} has the wrong number of columns.")
            rows.append(row)
            index += 1
        # Decode once: a literal '&amp;' in CSV must stay literal after a round trip.
        tables.append([
            [html.unescape(re.sub(r"<br\s*/?>", "\n", cell, flags=re.I).replace(r"\|", "|")) for cell in row]
            for row in rows
        ])
    return tables


def md_to_csv(text: str, delimiter: str = ",", table: int | None = None) -> str:
    tables = parse_tables(text)
    if not tables:
        raise ConversionError("No supported pipe table found; prose cannot be converted to CSV.")
    if table is None and len(tables) > 1:
        raise ConversionError(f"Found {len(tables)} tables; select one with --table (1-based).")
    selected = 1 if table is None else table
    if selected < 1 or selected > len(tables):
        raise ConversionError(f"--table must be between 1 and {len(tables)}.")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter)
    writer.writerows(tables[selected - 1])
    return output.getvalue()


def write_file(path: Path, content: bytes, force: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not force:
        with path.open("xb") as stream:
            stream.write(content)
        return
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".doc-bridge-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def convert_word(source: Path, destination: Path, force: bool, reference: Path | None) -> None:
    pandoc = find_pandoc()
    if not pandoc:
        raise ConversionError("Pandoc not found. Install pandoc or pip install 'codex-doc-bridge[word]'.")
    if reference and (source.suffix.lower() != ".md" or not reference.is_file() or reference.suffix.lower() != ".docx"):
        raise ConversionError("--reference-doc requires Markdown → DOCX and an existing .docx template.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    media = destination.with_name(destination.stem + ".assets")
    # Never merge extracted assets into a user directory, even with --force.
    if source.suffix.lower() == ".docx" and media.exists():
        raise ConversionError(f"Asset directory already exists: {media}; choose a new output name.")
    with tempfile.TemporaryDirectory(prefix="doc-bridge-") as working:
        temp = Path(working)
        output = temp / ("result" + destination.suffix.lower())
        markdown = "markdown+pipe_tables+raw_html"
        command = [pandoc, str(source), "--output", str(output), "--wrap=none"]
        if source.suffix.lower() == ".docx":
            compact_markdown = markdown + "-simple_tables-multiline_tables-grid_tables"
            command += ["--from=docx", f"--to={compact_markdown}", "--extract-media", media.name]
        else:
            command += [f"--from={markdown}", "--to=docx", "--resource-path", str(source.parent)]
            if reference:
                command += ["--reference-doc", str(reference)]
        result = subprocess.run(command, cwd=temp, capture_output=True, text=True)
        if result.returncode:
            raise ConversionError(f"Pandoc failed: {result.stderr.strip()}")
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        extracted = temp / media.name
        moved = False
        if extracted.exists():
            shutil.move(str(extracted), str(media))
            moved = True
        try:
            write_file(destination, output.read_bytes(), force)
        except BaseException:
            if moved:
                shutil.rmtree(media)
            raise


def convert(args: argparse.Namespace) -> dict:
    source, destination = args.source.resolve(), args.output.resolve()
    if not source.is_file():
        raise ConversionError(f"Input file not found: {source}")
    if source == destination:
        raise ConversionError("Input and output must be different files.")
    if destination.exists() and not args.force:
        raise ConversionError("Output already exists; choose a new path or use --force.")
    pair = (source.suffix.lower(), destination.suffix.lower())
    if pair not in {(".docx", ".md"), (".md", ".docx"), (".csv", ".md"), (".md", ".csv")}:
        raise ConversionError("Supported pairs: .docx ↔ .md and .csv ↔ .md. Legacy .doc is not supported.")
    if args.table is not None and pair != (".md", ".csv"):
        raise ConversionError("--table applies only to Markdown → CSV.")
    if args.reference_doc and pair != (".md", ".docx"):
        raise ConversionError("--reference-doc applies only to Markdown → DOCX.")
    if ".docx" in pair:
        convert_word(source, destination, args.force, args.reference_doc.resolve() if args.reference_doc else None)
    else:
        text = source.read_text(encoding=args.encoding)
        content = csv_to_md(text, args.delimiter) if pair[0] == ".csv" else md_to_csv(text, args.delimiter, args.table)
        write_file(destination, content.encode("utf-8"), args.force)
    return {"output": str(destination), "bytes": destination.stat().st_size}


def export_skill(destination: Path) -> dict:
    destination = destination.resolve()
    if destination.exists():
        raise ConversionError("Skill destination already exists; choose a new directory.")
    templates = Path(__file__).with_name("templates")
    if not templates.is_dir():
        raise ConversionError("Run export-skill from the installed package, not the standalone exported script.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".skill-") as working:
        root = Path(working) / "doc-bridge"
        (root / "scripts").mkdir(parents=True)
        (root / "agents").mkdir()
        shutil.copyfile(__file__, root / "scripts" / "doc_bridge.py")
        shutil.copyfile(templates / "SKILL.md", root / "SKILL.md")
        shutil.copyfile(templates / "openai.yaml", root / "agents" / "openai.yaml")
        root.rename(destination)
    return {"skill": str(destination)}


def delimiter(value: str) -> str:
    value = "\t" if value == r"\t" else value
    if len(value) != 1 or value in "\r\n\0\"":
        raise argparse.ArgumentTypeError("Delimiter must be one character other than newline, NUL or quote.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    conversion = sub.add_parser("convert", help="Convert DOCX ↔ MD or CSV ↔ MD")
    conversion.add_argument("source", type=Path)
    conversion.add_argument("-o", "--output", type=Path, required=True)
    conversion.add_argument("--force", action="store_true")
    conversion.add_argument("--encoding", default="utf-8-sig", help="Input encoding for CSV/Markdown; output is UTF-8")
    conversion.add_argument("--delimiter", type=delimiter, default=",")
    conversion.add_argument("--table", type=int)
    conversion.add_argument("--reference-doc", type=Path)
    sub.add_parser("doctor", help="Report optional Word backend availability")
    skill = sub.add_parser("export-skill", help="Export a self-contained Codex skill directory")
    skill.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            pandoc = find_pandoc()
            result = {"csv": "ready", "word": "ready" if pandoc else "missing-pandoc", "pandoc": pandoc}
        elif args.command == "export-skill":
            result = export_skill(args.destination)
        else:
            result = convert(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ConversionError, OSError, UnicodeError, LookupError, csv.Error) as exc:
        print(f"doc-bridge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
