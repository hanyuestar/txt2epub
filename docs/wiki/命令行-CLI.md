# 命令行（CLI）使用指南

适合批量、自动化、接入脚本的进阶用户。CLI 与 GUI 共用同一转换内核。

## 安装

```powershell
python -m pip install .
```

安装后可使用 `txt2epub` 命令；或从仓库源码直接运行：

```powershell
python -m src convert --input 小说.txt
```

> 仅本地开发时，也可只装运行依赖：`python -m pip install -r requirements.txt`

## 基本用法

```bash
txt2epub convert --input 小说.txt
```

默认在 TXT 同目录生成同名 `.epub`。完整参数示例：

```bash
txt2epub convert \
  --input 小说.txt \
  --output 输出.epub \
  --title "书名" \
  --author "作者" \
  --language zh \
  --cover 封面.png \
  --encoding utf-8 \
  --description "一句话简介" \
  --overwrite \
  --preserve-line-breaks
```

查看全部参数：`txt2epub convert --help`。

## 参数说明

| 参数 | 简写 | 说明 | 默认值 |
| --- | --- | --- | --- |
| `--input` | `-i` | 输入 TXT 路径（**必填**，必须是 `.txt`） | — |
| `--output` | `-o` | 输出 EPUB 路径 | 与输入同名、同目录 `.epub` |
| `--title` | `-t` | 书名（不填则自动识别） | 自动识别 |
| `--author` | `-a` | 作者（不填则自动识别） | 自动识别 |
| `--language` | `-l` | 语言代码 | 自动识别 |
| `--encoding` |  | 输入文件编码（不填则自动检测） | 自动检测 |
| `--identifier` |  | 书籍标识符（如 ISBN） | 自动生成 UUID |
| `--cover` | `-c` | 封面图片路径；封面为第一页，其后为扉页 | 无 |
| `--description` |  | 简介文字（写入扉页与 EPUB 元数据） | 自动识别 |
| `--description-file` |  | 从 TXT 文件读取简介（与 `--description` 互斥） | — |
| `--overwrite` |  | 允许覆盖已存在的输出 EPUB | **False（默认拒绝覆盖）** |
| `--preserve-line-breaks` |  | 保留每行硬换行（诗歌 / 预格式化文本用） | False（正文自动重排） |

> **CLI 与 GUI 的覆盖默认值不同**：CLI 默认 `--overwrite` 为 **False**（目标已存在会拒绝写入，需显式加 `--overwrite`）；GUI 默认 **True**（重跑即重生成）。

## 示例

指定输出路径与元数据：

```bash
txt2epub convert \
  --input ".\小说.txt" \
  --output ".\小说.epub" \
  --title "书名" \
  --author "作者" \
  --language zh \
  --cover ".\封面.png"
```

指定简介文件：

```bash
txt2epub convert --input book.txt --description-file intro.txt
```

手动指定编码（绕过自动检测）：

```bash
txt2epub convert --input book.txt --encoding gbk
```

## 安全与校验

- 目标文件已存在且未加 `--overwrite` 时，拒绝写入并提示；
- 输出路径不能与输入文件相同；
- 输入必须是 `.txt` 文件；
- 封面文件、`--description-file` 指定的文件必须存在，否则报错。

> 普通正文的硬换行会在段落内自动重排以适配屏幕；诗歌或预格式化文本请用 `--preserve-line-breaks`。
