# econ-brief — 经济学每日科研简报

每天自动抓取国内外经济学顶级期刊的最新论文，利用 DeepSeek AI 进行 10 维度深度分析，生成中英双语科研简报，通过邮件推送。

## 功能特性

- 📰 **多源抓取**: 12 本国际顶刊 + 11 本中文顶刊 + arXiv 预印本
- 🔓 **CNKI 突破**: 通过 `curl_cffi` 伪造 Chrome TLS 指纹，绕过知网反爬（HTTP 418）
- 🤖 **AI 分析**: DeepSeek 两阶段分析（评分筛选 → 10维深度分析）
- 🌐 **中英双语**: 中文叙述 + 英文术语保留
- 🇨🇳 **中文优先**: 简报中文期刊排最前，中英文分别设阈值和配额
- 📧 **邮件推送**: 每天早上 8:00 自动发送 HTML 邮件
- 💰 **极低成本**: ~$0.05-0.10/天

## 覆盖期刊

### 中文期刊（11 本）
经济研究 · 管理世界 · 中国社会科学 · 数量经济技术经济研究 · 世界经济 · 中国工业经济 · 经济学季刊 · 金融研究 · 中国农村经济 · 农业技术经济 · 中国农村观察

### 国际 Top 5
American Economic Review · Econometrica · Journal of Political Economy · Quarterly Journal of Economics · Review of Economic Studies

### 国际领域期刊
Journal of Finance · Journal of Financial Economics · Journal of Econometrics · AEJ: Applied Economics · AEJ: Economic Policy · AEJ: Macroeconomics · AEJ: Microeconomics

### 工作论文
arXiv (econ.GN, econ.EM, econ.TH)

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
- macOS（用于 `launchd` 自动调度）
- [DeepSeek API Key](https://platform.deepseek.com/)
- SMTP 邮箱服务（QQ邮箱、Brevo 等）

### 1. 克隆并安装

```bash
git clone https://github.com/anan920111-cloud/econ-brief.git
cd econ-brief
pip install -e .
pip install curl_cffi  # CNKI TLS 指纹伪装（必需）
```

### 2. 配置环境变量

在 `~/.zshrc` 中追加：

```bash
export DEEPSEEK_API_KEY="sk-xxx"        # DeepSeek API key
export SMTP_HOST="smtp.qq.com"          # SMTP 服务器
export SMTP_PORT="587"
export SMTP_USERNAME="xxx@qq.com"       # 发件邮箱
export SMTP_PASSWORD="xxx"              # SMTP 授权码
export EMAIL_FROM="xxx@qq.com"          # 同 SMTP_USERNAME
export EMAIL_TO="xxx@xxx.com"           # 接收简报的邮箱
export OPENALEX_EMAIL="xxx@xxx.com"     # OpenAlex 礼貌访问
```

### 3. 配置 launchd 自动调度

```bash
# 创建 plist 文件（路径改成你自己的）
cat > ~/Library/LaunchAgents/com.econ-brief.daily.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.econ-brief.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-l</string>
        <string>-c</string>
        <string>cd /Users/YOUR_USER/econ-brief && python3.12 -m econ_brief</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>8</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/econ-brief.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/econ-brief.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.econ-brief.daily.plist
```

每天早上 8:00 自动运行。如果当时电脑休眠，开机后自动补跑。

### 4. 手动运行

```bash
source ~/.zshrc
cd ~/econ-brief
python3.12 -m econ_brief           # 完整管线（抓取+分析+邮件）
python3.12 -m econ_brief --fetch-only  # 仅抓取，不分析
```

## 评分与配额

简报采用**两阶段筛选**，中文和英文分别设定阈值和配额：

| | 英文论文 | 中文论文 |
|---|---|---|
| **Stage 1 评分门槛** | ≥ 6.0 | ≥ 4.0（更低，补偿 DeepSeek 评分偏差） |
| **保底配额** | 无 | ≥ 5 篇（不够从低分补） |
| **每日上限** | ≤ 10 篇 | ≤ 10 篇 |
| **总计** | | 5~20 篇 |
| **排序** | | 中文优先 |
| **抓取范围** | 30 天 | 30 天 |

调整阈值（可选）：

```bash
export MIN_RELEVANCE_SCORE="5.5"      # 英文门槛
export MIN_RELEVANCE_SCORE_ZH="3.5"   # 中文门槛
export MIN_CHINESE_STAGE2="5"         # 中文保底
export MAX_CHINESE_STAGE2="10"        # 中文上限
export MAX_ENGLISH_STAGE2="10"        # 英文上限
export LOOKBACK_DAYS="30"             # 抓取天数
```

## 项目结构

```
econ-brief/
├── .github/workflows/                  # GitHub Actions（已禁用，本地 launchd 替代）
├── src/econ_brief/
│   ├── __main__.py                    # 主入口 + 管线编排
│   ├── config.py                      # 配置加载
│   ├── constants.py                   # 期刊 ISSN、URL 常量
│   ├── fetchers/                      # 数据抓取器
│   │   ├── openalex_fetcher.py        #   OpenAlex API
│   │   ├── arxiv_fetcher.py           #   arXiv API
│   │   ├── nber_fetcher.py            #   NBER RSS + JSON API
│   │   └── chinese_fetcher.py         #   中文期刊（curl_cffi + CNKI RSS）
│   ├── models/paper.py                # 统一 Paper 数据模型
│   ├── dedup/deduplicator.py          # 去重策略
│   ├── llm/                           # LLM 分析管线（DeepSeek）
│   │   ├── client.py                  #   OpenAI SDK 封装（DeepSeek 兼容）
│   │   ├── scorer.py                  #   Stage 1: 评分
│   │   ├── analyzer.py                #   Stage 2: 深度分析
│   │   └── prompts.py                 #   提示词模板
│   ├── output/                        # 输出生成
│   │   ├── markdown.py                #   Markdown 简报
│   │   ├── email_html.py              #   HTML 邮件
│   │   ├── email_sender.py            #   SMTP 发送
│   │   └── templates/                 #   邮件模板
│   └── state/tracker.py               # 状态持久化
├── config/
│   ├── journals.yaml                  # 期刊配置（加期刊改这里）
│   └── prompts.yaml                   # 提示词配置
└── output/briefings/                  # 生成的每日简报
```

## 添加新期刊

编辑 `config/journals.yaml`，在 `chinese_journals:` 下加：

```yaml
  - name: "期刊名"
    name_en: "English Name"
    issn: "XXXX-XXXX"
    has_rss: true
    cnki_rss: "https://rss.cnki.net/knavi/rss/CODE?pcode=CJFD,CCJD"
```

期刊代码（`CODE`）去知网搜期刊名，URL 里就能看到。国际期刊同理，加在 `international_field:` 下。

## 成本估算

DeepSeek API 定价（美元/百万 tokens）：

| 模型 | 输入 | 输出 |
|---|---|---|
| deepseek-chat (V3) | $0.27 | $1.10 |

预估（30 天窗口，~200 篇评分 + ~15 篇深度分析）：

| 阶段 | 每天 | 每月 |
|---|---|---|
| Stage 1: Scoring | ~$0.02 | ~$0.60 |
| Stage 2: Analysis | ~$0.06 | ~$1.80 |
| Executive Summary | ~$0.01 | ~$0.30 |
| **总计** | **~$0.10** | **~$3.00** |

> 💡 首次运行（30 天无去重）约 $0.10，日常去重后更低。

## 已知限制

- **CNKI 反爬**: `curl_cffi` 伪装 TLS 指纹可绕过，但 CNKI 可能未来加强检测
- **NBER**: 中国 IP 被 NBER 封锁（HTTP 403），arXiv 已覆盖大部分 NBER 论文
- **邮件频率**: 每天一封，只在 Mac 开机时发送
- **DeepSeek 评分偏差**: 对中文论文评分偏低，已通过独立的 `MIN_RELEVANCE_SCORE_ZH` 补偿

## License

MIT
