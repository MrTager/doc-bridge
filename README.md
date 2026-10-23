# doc-bridge

面向 Codex 的本地文档转换工具：**DOCX ↔ Markdown、CSV ↔ Markdown 表格**。
把确定性的转换交给脚本，让模型只读取和修改相关文本。自带 `export-skill`，
可生成包含转换脚本、无需克隆源码即可使用的 Codex skill。

## 安装

需要 Python 3.10+。克隆本仓库后，在仓库目录执行：

```sh
python3 -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install '.[word]'
doc-bridge doctor
```

`word` 可选依赖包含 Pandoc 二进制；也可自行安装 Pandoc，并仅执行 `pip install .`。
CSV 转换仅使用 Python 标准库，不需要 Pandoc、模型 API 或 API key。

## 四种转换

```sh
doc-bridge convert input.docx -o work/input.md
# 在 Markdown 中修改需要修改的部分，再导出到新文件：
doc-bridge convert work/input.md -o output.docx

doc-bridge convert input.csv -o work/table.md
doc-bridge convert work/table.md -o output.csv
```

文件扩展名决定转换方向。输入与输出必须不同；已有输出默认拒绝覆盖，确认后可用
`--force`。Word 提取的图片保存在 Markdown 旁的 `<stem>.assets` 目录；移动 Markdown
时请一起移动该目录。为保护已有文件，该 assets 目录存在时，即使用 `--force` 也拒绝合并。

```sh
doc-bridge convert work/input.md -o styled.docx --reference-doc template.docx
doc-bridge convert input.csv -o table.md --encoding gb18030 --delimiter ';'
doc-bridge convert tables.md -o second.csv --table 2
```

`--encoding` 指定文本输入编码（默认 `utf-8-sig`，兼容 UTF-8 BOM），输出始终为 UTF-8。
`--delimiter` 默认逗号，支持 `';'` 或 `'\t'`；非默认分隔符需要在来回转换时分别指定。
输出 CSV 使用标准 CSV 引用规则和 CRLF 记录换行。
成功命令输出一行 JSON 元数据，不会把全文打印进模型上下文；错误退出码为 1，参数错误为 2。

## 生成 Codex skill

```sh
doc-bridge export-skill ./generated/doc-bridge
# 或直接导出到你配置的 Codex skills 目录（目标目录须不存在）：
doc-bridge export-skill "$HOME/.codex/skills/doc-bridge"
```

生成结构：

```text
doc-bridge/
├── SKILL.md
├── agents/openai.yaml
└── scripts/doc_bridge.py
```

生成的 skill 自带独立脚本，不依赖本仓库路径；Word 仍需要 Pandoc 或运行脚本的 Python
环境中已安装 `pypandoc_binary`。重新加载 skills 后可请求：
“使用 $doc-bridge 将这份 Word 转为 Markdown，只修改第二节，再导出新的 Word。”

生成 skill 是封装转换工作流，不是自动理解任意 Word 后生成领域专业知识 skill。
后者需要另外设计提取、审阅和知识组织流程。

## 格式边界与数据安全

- Word 当前指 `.docx`，不支持旧版二进制 `.doc`。
- Word 转换适合正文、标题、列表、链接、普通表格和图片等内容优先的编辑；不承诺无损
  保留页眉页脚、分页、批注、修订、文本框、复杂合并表格或原始排版。
  `--reference-doc` 用于样式参考，不会恢复原文件的一切内容或布局。重要交付须人工/渲染检查。
- CSV 第一行视为表头，所有记录必须列数一致；保留字符串，不把 `00123` 自动转成数值。
  Markdown → CSV 仅接受有首尾 `|`、至少三个 `-` 分隔符的 pipe table，忽略围栏代码块；
  多表必须显式选择 `--table N`，不会把正文推测为表格。
- CSV 单元格中的特殊字符、换行和边缘空白编码成 HTML 实体；请保留这些实体。
  支持单元格字符串的往返，不保证原始 CSV 的 BOM、引号风格或字节级一致性。
  手写 Markdown 表格中的 HTML 实体会被解码，`<br>` 会转成单元格换行；其他 Markdown
  内联语法保留为文字，不作为完整 GFM 解析器使用。
- 公式形式字符串不会被擅自改变；用 Excel 等软件打开 CSV 前应考虑 CSV 公式注入风险。
- 不调用模型、不上传文档到转换服务。但 Pandoc 处理 Markdown 中远程图片时可能联网；
  保密/离线任务请仅使用可信本地资源，并在需要时限制运行环境的网络访问。
- 不执行文档中的指令、宏或嵌入脚本；仍建议对不可信文件使用隔离环境和维护中的 Pandoc。

## 会更快、更省 token 吗？

可行，但主要收益来自**重复转换交给脚本、只读取相关段落、避免把整份文档和图片放进上下文**，
不是 Markdown 扩展名本身。对于原本已经高效提取文本的流程，收益可能有限；小文件还可能
增加转换开销。本项目没有跑过真实模型任务对照，不声称固定提速或 token 节省比例。
建议同一份文档、同一修改任务分别记录总耗时、输入/输出 token 和最终格式质量再比较。

## 开发与测试

```sh
python -m pip install -e '.[word,dev]'
python -m pytest -q
python -m build
```

测试覆盖特殊字符、中文、空值、前导零、单元格换行、多表选择、覆盖保护、skill 独立执行、
Word 内容往返及样式参考。缺少 Pandoc 时 Word 测试跳过；CI 安装 Word 依赖后运行。
