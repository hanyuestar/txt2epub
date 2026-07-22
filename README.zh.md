# txt2epub

[English](README.md) | [中文](README.zh.md)

`txt2epub` 是一个将 TXT 小说、长文本转换为 EPUB 的命令行工具。它针对常见中文 TXT 资源和英文标题格式进行了兼容，不依赖图形界面。

## 环境要求

- Python 3.10 或更高版本

## 安装

安装项目及其命令行工具：

```powershell
python -m pip install .
```

如果只在本地开发时使用，也可以只安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

## 转换图书

```powershell
txt2epub convert --input .\小说.txt
```

默认会在 TXT 文件旁生成同名 EPUB。也可以指定输出路径和元数据：

```powershell
txt2epub convert `
  --input .\小说.txt `
  --output .\小说.epub `
  --title "书名" `
  --author "作者" `
  --language zh `
  --cover .\封面.png
```

为避免误覆盖，目标文件已存在时会拒绝写入；确认需要替换时请添加 `--overwrite`。输出路径也不能与输入文件相同。Python API 同样默认拒绝覆盖，需显式传入 `overwrite=True`。

普通正文的硬换行会在段落内自动重排，以适应字号和屏幕宽度；诗歌或预格式化文本需要保留每一行时，请使用 `--preserve-line-breaks`。

指定封面时，封面会是第一页；其后是展示书名、作者、字数和章节数的扉页。两页都不会作为目录项出现。

TXT 开头包含 `书名：`、`作者：`、`简介：` 等字段时会自动读取。其他来源可通过 `--description "..."` 或 `--description-file .\description.txt` 将简介写入扉页和 EPUB 元数据。

如果是直接从仓库运行、尚未安装项目，可使用：

```powershell
python -m src convert --input .\小说.txt
```

完整参数请查看 `txt2epub convert --help`。`--encoding` 可手动指定输入编码；未指定时会依次尝试 UTF-8、GB18030、GBK 和自动检测。

## 章节识别

已兼容以下常见标题形式：

- 中文标题，如 `第一章 标题`、`第二回 标题`、`第 十二 章 标题`、`012 标题`。
- 分卷标题，如 `第一卷 标题`、`【第一卷：标题】`。
- 数字标题，如 `001 [标题]`、`1. 标题`。
- 英文 `Chapter`、`Book`、`Part`、`Volume` 标题。
- 特殊章节，如 `序章`、`楔子`、`前言`、`终章`、`尾声`、`后记`、`附录`、`番外`。

工具会移除正文前重复的纯标题目录，处理抓取内容中的常见 HTML 段落标签，并解码 `&amp;` 等 HTML 实体。小数和时间戳不会被误判为章节标题。

当无法可靠判断章节结构时，正文会保留为一个 EPUB 章节，避免因普通段落空行被错误拆分。

## 开发检查

安装开发检查工具后，可运行：

```powershell
python -m pip install ruff
make check
```

下面的脚本可扫描 TXT 中的 HTML 标签、实体、替换字符和无效 XML 控制字符：

```powershell
python scripts\check_txt_compatibility.py tests
```

## 许可

本项目采用 [MIT License](LICENSE) 发布。
