# econ-brief — 经济学每日科研简报

每天自动抓取国内外经济学顶级期刊的最新论文，利用 Claude AI 进行 10 维度深度分析，生成中英双语科研简报，通过邮件推送。

## 功能特性

- 📰 **多源抓取**: 覆盖 12 本国际顶刊 + 9 本中文顶刊 + NBER 工作论文 + arXiv 预印本
- 🤖 **AI 分析**: Claude 两阶段分析（Haiku 评分筛选 → Sonnet 10维深度分析）
- 🌐 **中英双语**: 中文叙述 + 英文术语保留
- 📧 **邮件推送**: 每天早上 8:17（北京时间）自动发送 HTML 邮件
- 📝 **本地存档**: Markdown 简报自动提交到仓库
- 💰 **极低成本**: ~$0.20/天，~$6/月

## 覆盖期刊

### 国际 Top 5
American Economic Review · Econometrica · Journal of Political Economy · Quarterly Journal of Economics · Review of Economic Studies

### 国际领域期刊
Journal of Finance · Journal of Financial Economics · Journal of Econometrics · AEJ: Applied Economics · AEJ: Economic Policy · AEJ: Macroeconomics · AEJ: Microeconomics

### 中文期刊
经济研究 · 管理世界 · 中国社会科学 · 数量经济技术经济研究 · 世界经济 · 中国工业经济 · 经济学季刊 · 金融研究 · 中国农村经济

### 工作论文
NBER Working Papers · arXiv (econ.GN, econ.EM, econ.TH)

## 分析维度

每篇论文从以下 10 个维度进行深度分析：

1. **研究主题** — 核心研究问题及其在文献中的位置
2. **方法与数据** — 实证策略、模型类型、数据来源
3. **创新点** — 相对现有文献的真正创新
4. **理论框架** — 背后的经济学理论或概念模型
5. **实证策略** — 识别策略、内生性处理、稳健性检验
6. **主要发现** — 核心结果及其经济含义
7. **写作特点** — 结构、清晰度、叙事方式
8. **局限性** — 内外部有效性、数据约束等
9. **可扩展方向** — 后续研究可能性
10. **对中国研究的启示** — 对中国经济学研究的参考价值

## 快速开始

### 前置条件

- Python 3.11+
- [Anthropic API Key](https://console.anthropic.com/) (Claude)
- SMTP 邮箱服务（推荐 [Brevo](https://www.brevo.com/) 免费 300 封/天）

### 1. 克隆并安装

```bash
git clone https://github.com/YOUR_USERNAME/econ-brief.git
cd econ-brief
pip install -e .
```

### 2. 配置 GitHub Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude API 密钥 |
| `OPENALEX_EMAIL` | 你的邮箱（用于 OpenAlex 高频率访问） |
| `SMTP_HOST` | SMTP 服务器地址（如 `smtp.brevo.com`） |
| `SMTP_PORT` | SMTP 端口（通常 `587`） |
| `SMTP_USERNAME` | SMTP 登录用户名 |
| `SMTP_PASSWORD` | SMTP 密码/API Key |
| `EMAIL_FROM` | 发件人地址 |
| `EMAIL_TO` | 收件人地址（多个用逗号分隔） |
| `GH_PAT` | GitHub Personal Access Token（用于跨分支推送状态） |

### 3. 启用 GitHub Actions

推送代码到 GitHub 后，Actions 会按 cron 计划自动运行：

- **自动运行**: 每天 0:17 UTC（北京时间 8:17）
- **手动运行**: Actions → Daily Economics Brief → Run workflow

### 4. 本地测试

```bash
# 测试抓取（不调用 LLM）
ANTHROPIC_API_KEY=your_key python -m econ_brief --fetch-only

# 完整运行
ANTHROPIC_API_KEY=your_key \
SMTP_HOST=smtp.brevo.com \
SMTP_PORT=587 \
SMTP_USERNAME=your_login \
SMTP_PASSWORD=your_password \
EMAIL_FROM=bot@example.com \
EMAIL_TO=you@example.com \
python -m econ_brief
```

## 项目结构

```
econ-brief/
├── .github/workflows/daily_brief.yml  # GitHub Actions 调度
├── src/econ_brief/
│   ├── __main__.py                    # 主入口 + 管线编排
│   ├── config.py                      # 配置加载
│   ├── constants.py                   # 期刊 ISSN、URL 常量
│   ├── fetchers/                      # 数据抓取器
│   │   ├── openalex_fetcher.py        #   OpenAlex API
│   │   ├── arxiv_fetcher.py           #   arXiv API
│   │   ├── nber_fetcher.py            #   NBER JSON API
│   │   └── chinese_fetcher.py         #   中文期刊（NCPSSD + RSS）
│   ├── models/paper.py                # 统一 Paper 数据模型
│   ├── dedup/deduplicator.py          # 三重去重策略
│   ├── llm/                           # LLM 分析管线
│   │   ├── client.py                  #   Anthropic SDK 封装 + 缓存
│   │   ├── scorer.py                  #   Stage 1: Haiku 评分
│   │   ├── analyzer.py                #   Stage 2: Sonnet 深度分析
│   │   └── prompts.py                 #   提示词模板
│   ├── output/                        # 输出生成
│   │   ├── markdown.py                #   Markdown 简报
│   │   ├── email_html.py              #   HTML 邮件
│   │   └── email_sender.py            #   SMTP 发送
│   └── state/tracker.py               # 状态持久化
├── config/
│   ├── journals.yaml                  # 期刊配置
│   └── prompts.yaml                   # 提示词配置
└── output/briefings/                  # 生成的每日简报
```

## 成本估算

| 项目 | 每天 | 每月 |
|---|---|---|
| Claude Haiku (Scoring) | $0.03 | $0.90 |
| Claude Sonnet (Analysis) | $0.15 | $4.50 |
| OpenAlex / arXiv / NBER API | 免费 | 免费 |
| Brevo 邮件 | 免费 (300封/天) | 免费 |
| GitHub Actions | 免费 (2000分钟/月) | 免费 |
| **总计** | **~$0.20** | **~$5.40** |

## 自定义

### 调整期刊列表

编辑 `config/journals.yaml` 添加或移除期刊。

### 调整相关性阈值

默认只分析评分 ≥ 6.0/10 的论文。在 Actions 中设置 `MIN_RELEVANCE_SCORE` 环境变量调整。

### 调整分析深度

默认最多分析 30 篇论文。通过 `MAX_STAGE2_PAPERS` 环境变量调整。

## 已知限制

- **中文期刊覆盖**: 由于 CNKI 无公开 API，中文期刊覆盖率为 60-80%（通过 OpenAlex + NCPSSD）
- **NBER API**: 使用非官方 API，未来可能变化（OpenAlex 有延迟收录可作为备用）
- **GitHub Actions 延迟**: 调度可能延迟 5-30 分钟
- **摘要依赖**: 分析质量取决于可用摘要的质量

## License

MIT
