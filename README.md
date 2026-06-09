## 测试用例自动生成工具

本项目是一个智能测试用例生成工具：输入需求文件（或目录），输出高质量测试用例文档（Excel/CSV）。

### 核心功能

- **智能生成**：接入大模型（LLM），语义分析需求，智能拆分测试点，生成针对性用例
- **用例评审**：自动评审用例质量，识别重复用例、缺失场景
- **自动修复**：评审后自动合并重复用例、补充缺失场景
- **图片OCR**：支持界面截图，自动识别按钮、输入框等UI元素

### 支持输入格式

- 文本类：`.txt` `.md` `.markdown`
- 办公文档：`.docx` `.pdf`
- 表格：`.csv` `.xlsx` `.xlsm`
- 结构化：`.json`
- 图片 OCR：`.png` `.jpg` `.jpeg` `.bmp` `.webp` `.tiff`

说明：`--input` 可传单文件，也可传目录，目录下支持文件会自动批量解析。

### 输出字段

输出用例固定包含以下列：

- 用例模块
- 用例ID
- 用例名称
- 验收目的
- 预置条件
- 测试过程
- 预期结果
- 用例类型

### 快速使用

```bash
python -m test_tool.main --input "你的需求路径" --output-dir out --format both
```

可选参数：

- `--format excel`：只输出 Excel
- `--format csv`：只输出 CSV
- `--format both`：同时输出 Excel + CSV（默认）
- `--format all`：输出 Excel + CSV + 导图（`.xmind` + `.mm`）
- `--min-cases 100`：最少生成条数（默认 300）
- `--use-llm`：使用LLM智能生成（需配置API Key）

### 输出文件

- `out/test_cases.xlsx`
- `out/test_cases.csv`

## 大模型配置（智能生成）

使用智能生成功能需配置LLM API Key：

### 环境变量配置

```bash
# DeepSeek（推荐，性价比高）
export LLM_API_KEY="sk-xxxxx"
export LLM_PROVIDER="deepseek"
export LLM_BASE_URL="https://api.deepseek.com/v1"

# OpenAI
export LLM_API_KEY="sk-xxxxx"
export LLM_PROVIDER="openai"
export LLM_BASE_URL="https://api.openai.com/v1"

# Anthropic Claude
export LLM_API_KEY="sk-ant-xxxxx"
export LLM_PROVIDER="anthropic"
```

获取 DeepSeek API Key：https://platform.deepseek.com/api_keys

## 可视化网页界面

安装依赖后，执行：

```bash
python -m test_tool.web
```

如果你不在项目目录下，也可以直接运行：

```bash
python c:\cursor_workplace\run_web.py
```

然后在浏览器打开：`http://127.0.0.1:5000`

网页支持：

- 一次上传多个需求文件/图片
- 选择生成模式（智能生成/模板生成）
- 启用用例评审
- 启用自动修复
- 选择输出格式（Excel / CSV / 两者）
- 可设置最少用例生成条数（默认 100）
- 在线下载生成结果
- 查看评审报告和改进建议

## 智能生成 vs 模板生成

| 特性 | 智能生成 (LLM) | 模板生成 |
|------|---------------|----------|
| 测试点拆分 | 语义分析，智能拆分 | 关键词匹配 |
| 用例内容 | 针对性强，定制化 | 模板固定，通用化 |
| 预置条件 | 根据功能定制 | 固定模板 |
| 用例评审 | 支持 | 不支持 |
| 自动修复 | 支持 | 不支持 |
| 配置要求 | 需LLM API Key | 无需配置 |

## 依赖安装

```bash
pip install -r requirements.txt
```

