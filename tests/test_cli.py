import subprocess
import sys
import base64
import os
from pathlib import Path

import pytest

from doc_bridge.cli import find_pandoc, main


def test_skill_local_backend(tmp_path, monkeypatch):
    import doc_bridge.cli as cli

    monkeypatch.setattr(cli, "__file__", str(tmp_path / "scripts" / "doc_bridge.py"))
    backend = tmp_path / "bin" / ("pandoc.exe" if os.name == "nt" else "pandoc")
    backend.parent.mkdir()
    backend.write_text("placeholder", encoding="utf-8")
    backend.chmod(0o755)
    assert cli.find_pandoc() == str(backend)


def test_repository_skill_is_current(tmp_path):
    exported = tmp_path / "doc-bridge"
    assert main(["export-skill", str(exported)]) == 0
    repository_skill = Path(__file__).resolve().parents[1] / "skills" / "doc-bridge"
    if not repository_skill.exists():
        pytest.skip("Source distribution does not include the repository skill snapshot")
    for relative in ["SKILL.md", "agents/openai.yaml", "scripts/doc_bridge.py"]:
        assert (exported / relative).read_bytes() == (repository_skill / relative).read_bytes()


def test_no_overwrite_and_invalid_pair(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("a\n001\n", encoding="utf-8")
    output = tmp_path / "out.md"
    assert main(["convert", str(source), "-o", str(output)]) == 0
    original = output.read_bytes()
    assert main(["convert", str(source), "-o", str(output)]) == 1
    assert output.read_bytes() == original
    assert main(["convert", str(source), "-o", str(output), "--force"]) == 0
    assert main(["convert", str(source), "-o", str(tmp_path / "out.doc")]) == 1
    assert main(["convert", str(source), "-o", str(source), "--force"]) == 1


def test_encoding_and_exported_skill(tmp_path):
    source = tmp_path / "in.csv"
    source.write_bytes("姓名,编号\n小明,001\n".encode("gb18030"))
    output = tmp_path / "out.md"
    assert main(["convert", str(source), "-o", str(output), "--encoding", "gb18030"]) == 0
    skill = tmp_path / "doc-bridge"
    assert main(["export-skill", str(skill)]) == 0
    assert main(["export-skill", str(skill)]) == 1
    result = subprocess.run([sys.executable, str(skill / "scripts/doc_bridge.py"), "convert", str(output), "-o", str(tmp_path / "out.csv")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "小明,001" in (tmp_path / "out.csv").read_text(encoding="utf-8")


@pytest.mark.skipif(not find_pandoc(), reason="requires Pandoc")
def test_word_round_trip(tmp_path):
    markdown = tmp_path / "source.md"
    markdown.write_text("# 测试标题\n\n正文 **加粗** 与 [链接](https://example.com)。\n\n| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |\n", encoding="utf-8")
    word = tmp_path / "result.docx"
    back = tmp_path / "back.md"
    assert main(["convert", str(markdown), "-o", str(word)]) == 0
    assert word.read_bytes().startswith(b"PK")
    assert main(["convert", str(word), "-o", str(back)]) == 0
    text = back.read_text(encoding="utf-8")
    for item in ["测试标题", "正文", "加粗", "example.com", "苹果"]:
        assert item in text
    assert "|" in text
    assert "------------------------------" not in text
    assert main(["convert", str(markdown), "-o", str(tmp_path / "styled.docx"), "--reference-doc", str(word)]) == 0


def test_missing_pandoc(tmp_path, monkeypatch):
    import doc_bridge.cli as cli

    monkeypatch.setattr(cli, "find_pandoc", lambda: None)
    source = tmp_path / "in.md"
    source.write_text("hello", encoding="utf-8")
    assert main(["convert", str(source), "-o", str(tmp_path / "out.docx")]) == 1
    assert not (tmp_path / "out.docx").exists()


@pytest.mark.skipif(not find_pandoc(), reason="requires Pandoc")
def test_word_images_and_asset_collision(tmp_path):
    image = tmp_path / "pixel.png"
    image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="))
    source = tmp_path / "带图片.md"
    source.write_text("# 图片\n\n![像素](pixel.png)\n", encoding="utf-8")
    word = tmp_path / "image.docx"
    assert main(["convert", str(source), "-o", str(word)]) == 0
    extracted = tmp_path / "work" / "image.md"
    assert main(["convert", str(word), "-o", str(extracted)]) == 0
    assets = extracted.with_name("image.assets")
    assert list(assets.rglob("*.png"))
    original = extracted.read_bytes()
    assert main(["convert", str(word), "-o", str(extracted), "--force"]) == 1
    assert extracted.read_bytes() == original
    assert main(["convert", str(extracted), "-o", str(tmp_path / "round-trip.docx")]) == 0
