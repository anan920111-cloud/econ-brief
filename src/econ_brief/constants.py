"""Journal metadata, ISSNs, and URL constants."""

# ── International Top 5 ──────────────────────────────────────────────

INTL_TOP5 = [
    {
        "name": "American Economic Review",
        "issn": "0002-8282",
        "publisher": "AEA",
        "tier": "intl_top5",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "美国经济评论",
    },
    {
        "name": "Econometrica",
        "issn": "0012-9682",
        "publisher": "Wiley / Econometric Society",
        "tier": "intl_top5",
        "has_rss": True,
        "rss_url": "https://onlinelibrary.wiley.com/feed/14680262",
        "name_zh": "计量经济学",
    },
    {
        "name": "Journal of Political Economy",
        "issn": "0022-3808",
        "publisher": "University of Chicago Press",
        "tier": "intl_top5",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "政治经济学杂志",
    },
    {
        "name": "Quarterly Journal of Economics",
        "issn": "0033-5533",
        "publisher": "Oxford University Press",
        "tier": "intl_top5",
        "has_rss": True,
        "rss_url": "https://academic.oup.com/rss/site_5504/3365.xml",
        "name_zh": "经济学季刊",
    },
    {
        "name": "Review of Economic Studies",
        "issn": "0034-6527",
        "publisher": "Oxford University Press",
        "tier": "intl_top5",
        "has_rss": True,
        "rss_url": "https://academic.oup.com/rss/site_5508/3404.xml",
        "name_zh": "经济研究评论",
    },
]

# ── International Field Journals ─────────────────────────────────────

INTL_FIELD = [
    {
        "name": "Journal of Finance",
        "issn": "0022-1082",
        "publisher": "Wiley / AFA",
        "tier": "intl_field",
        "has_rss": True,
        "rss_url": "https://onlinelibrary.wiley.com/feed/15406261",
        "name_zh": "金融学杂志",
    },
    {
        "name": "Journal of Financial Economics",
        "issn": "0304-405X",
        "publisher": "Elsevier",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "金融经济学杂志",
    },
    {
        "name": "Journal of Econometrics",
        "issn": "0304-4076",
        "publisher": "Elsevier",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "计量经济学杂志",
    },
    {
        "name": "AEJ: Applied Economics",
        "issn": "1945-7782",
        "publisher": "AEA",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "美国经济杂志：应用经济学",
    },
    {
        "name": "AEJ: Economic Policy",
        "issn": "1945-7731",
        "publisher": "AEA",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "美国经济杂志：经济政策",
    },
    {
        "name": "AEJ: Macroeconomics",
        "issn": "1945-7707",
        "publisher": "AEA",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "美国经济杂志：宏观经济学",
    },
    {
        "name": "AEJ: Microeconomics",
        "issn": "1945-7669",
        "publisher": "AEA",
        "tier": "intl_field",
        "has_rss": False,
        "rss_url": None,
        "name_zh": "美国经济杂志：微观经济学",
    },
]

# ── Chinese Top Journals ─────────────────────────────────────────────

CHINESE_JOURNALS = [
    {
        "name": "经济研究",
        "name_en": "Economic Research Journal",
        "issn": "0577-9154",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "管理世界",
        "name_en": "Management World",
        "issn": "1002-5502",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "中国社会科学",
        "name_en": "Social Sciences in China",
        "issn": "1002-4921",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "数量经济技术经济研究",
        "name_en": "Journal of Quantitative & Technological Economics",
        "issn": "1000-3894",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "世界经济",
        "name_en": "The Journal of World Economy",
        "issn": "1002-9621",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "中国工业经济",
        "name_en": "China Industrial Economics",
        "issn": "1006-480X",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "经济学季刊",
        "name_en": "China Economic Quarterly",
        "issn": "2095-1086",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "金融研究",
        "name_en": "Journal of Financial Research",
        "issn": "1002-7246",
        "tier": "chinese_top",
        "rss_url": None,
    },
    {
        "name": "中国农村经济",
        "name_en": "Chinese Rural Economy",
        "issn": "1002-8870",
        "tier": "chinese_top",
        "rss_url": "https://zgncjj.ajcass.com/RSS/CN",
    },
]


def all_international_journals() -> list[dict]:
    """Return combined list of all international journals."""
    return INTL_TOP5 + INTL_FIELD


def all_journals() -> list[dict]:
    """Return combined list of all journals."""
    return INTL_TOP5 + INTL_FIELD + CHINESE_JOURNALS


def all_issns() -> list[str]:
    """Return all journal ISSNs."""
    return [j["issn"] for j in all_journals()]


# ── arXiv Categories ─────────────────────────────────────────────────

ARXIV_CATEGORIES = ["econ.GN", "econ.EM", "econ.TH"]

# ── NBER API ─────────────────────────────────────────────────────────

NBER_API_URL = (
    "https://www.nber.org/api/v1/working_page_listing/"
    "contentType/working_paper/_/_/search"
)

# ── Chinese Journal Sources ──────────────────────────────────────────

# NCPSSD base URL
NCPSSD_BASE = "https://m.ncpssd.cn"

# Chinese journal RSS URLs (verified or highly likely)
CHINESE_RSS_URLS: dict[str, str] = {
    "中国农村经济": "https://zgncjj.ajcass.com/RSS/CN",
}
