# txt2epub · TXT 转 EPUB 工具（含图形界面）

把小说 / 长文本 TXT 文件转换为 EPUB 3 电子书。支持**命令行（CLI）**与**图形界面（GUI）**两种用法，GUI 专为不想敲命令的用户设计。

> 本项目在 [hehetoshang/txt2epub](https://github.com/hehetoshang/txt2epub) 基础上新增了 Tkinter 图形界面与 PyInstaller 单文件打包，命令行功能完全保留。

## 功能特性

- 自动识别章节（中文「第一章 / 第N卷 / 序章 / 楔子」、英文 `Chapter / Volume`、纯数字编号等）
- 自动探测文件编码（UTF-8 / GB18030 / GBK）
- 自动提取书名、作者、简介等元数据写入 EPUB
- 支持封面图
- **新增图形界面**：批量选文件 / 文件夹、可视化进度、一键转换

## 快速开始（图形界面，推荐）

1. 到 [Releases](https://github.com/hanyuestar/txt2epub/releases) 下载 `txt2epub-gui.exe`
2. 双击运行（Windows 64 位，单文件，**无需安装 Python**）
3. 使用步骤：
   - 点「**选择文件…**」可一次多选多个 TXT；或点「**选择文件夹…**」自动扫描该目录下所有 `.txt`
   - 文件列表中可逐条点「**移除**」剔除不需要的文件，或点「**清空列表**」全部清空
   - 点「**浏览…**」选择转换后的输出目录
   - 确认无误后点底部「**确认转换**」
   - 等待进度条走完，弹窗显示「转换完成」及成功 / 失败统计
4. 转换后的 `.epub` 生成在你指定的输出目录，文件名与源 TXT 同名

> 转换在后台线程执行，界面不会卡死；单个文件失败不影响其余文件。

## 命令行用法

```bash
txt2epub convert --input 小说.txt \
  [--output 输出.epub] \
  [--title 书名] [--author 作者] [--language zh] \
  [--cover 封面.jpg] [--encoding utf-8] \
  [--overwrite] [--preserve-line-breaks] [--description 简介]
```

更完整的命令行说明见 [命令行-CLI 使用指南](docs/wiki/命令行-CLI.md)。

## 从源码构建 exe

需要 Python 3.10+ 与 pip：

```bash
pip install -r requirements.txt pyinstaller
pyinstaller txt2epub-gui.spec --noconfirm
```

产物在 `dist/txt2epub-gui.exe`（单文件，23MB 左右）。

## 项目结构

| 路径 | 说明 |
|------|------|
| `src/txt2epub.py` | 核心转换逻辑（CLI 与 GUI 共用，**未改动**） |
| `src/__main__.py` | 命令行入口 |
| `src/gui/` | Tkinter 图形界面（本次新增） |
| `txt2epub-gui.spec` | PyInstaller 单文件打包配置 |
| `PRD_GUI.md` / `ARCH_GUI.md` | GUI 增量需求与设计文档 |

## 使用文档

完整使用手册（GUI / CLI 用法、章节识别、编码兼容性、常见问题、从源码构建）见 [**`docs/wiki/Home.md`**](docs/wiki/Home.md)。

## 已知问题 / 待办

- ~~GBK/GB18030 编码识别问题~~ 已在 **v1.0.0（`026b339`）** 修复：`read_book_text` 曾因 charset_normalizer 把中文误判为韩文编码（cp949）导致乱码，现改为按 CJK 汉字占比重排候选，GBK/GB18030 文件正确解码（详见 [编码与兼容性](docs/wiki/编码与兼容性.md)）。
- v1 不支持中途中止、不暴露高级参数（编码 / 封面 / 标题等走自动识别；需手动控制请用 CLI）。

## 许可

请参考上游仓库许可协议。
