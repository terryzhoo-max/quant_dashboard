"""
AlphaCore · V21.2 信号预警监控器
================================
职责:
  1. 扫描缓存中的 JCS / VIX 最新值
  2. 判断是否触发预警阈值 (回测校准后)
  3. Cooldown 去重 (同一信号 N 小时内不重复)
  4. 写入 SQLite 持久化
  5. 多渠道推送: 浏览器 (前端轮询) + Server酱(微信) + Email(SMTP)

阈值校准依据:
  - VIX > 30: P95 (5年1283天, 仅66天触发, ~1次/月)
  - VIX > 35: P99 (极端恐慌, 仅8天, ~1次/半年)
  - JCS < 25: P22 (Monte Carlo 5000次, ~5次/月)
"""

import json
import os
import threading
from datetime import datetime, timedelta
from services.logger import get_logger

logger = get_logger("ac.alert")

# ═══════════════════════════════════════════════════
#  预警规则配置 (回测校准后)
# ═══════════════════════════════════════════════════

ALERT_RULES = [
    {
        "id": "jcs_low",
        "name": "JCS 低置信度",
        "check": lambda s: s.get("jcs_score", 100) < 25,
        "value_key": "jcs_score",
        "severity": "warning",
        "icon": "⚠️",
        "title_tpl": "JCS 低置信度 ({value:.1f} < 25)",
        "detail_tpl": "多引擎信号分歧较大 (JCS={value:.1f})，建议暂停操作等待方向确认。当前仓位建议: {pos}%",
        "cooldown_hours": 8,
    },
    {
        "id": "vix_panic",
        "name": "VIX 恐慌预警",
        "check": lambda s: (s.get("vix_val") or 0) > 30,
        "value_key": "vix_val",
        "severity": "critical",
        "icon": "🚨",
        "title_tpl": "VIX 恐慌 ({value:.1f} > 30)",
        "detail_tpl": "全球恐慌指数升温 (VIX={value:.1f})，注意仓位风控。5年回测: VIX>30后5日自然回落概率84.8%",
        "cooldown_hours": 4,
    },
    {
        "id": "vix_extreme",
        "name": "VIX 极端恐慌",
        "check": lambda s: (s.get("vix_val") or 0) > 35,
        "value_key": "vix_val",
        "severity": "critical",
        "icon": "🛑",
        "title_tpl": "VIX 极端恐慌 ({value:.1f} > 35)",
        "detail_tpl": "VIX={value:.1f} 触发全策略风控降权。规则: 仓位上限30%，禁止新建仓。历史5年仅8天触发此级别。",
        "cooldown_hours": 2,
    },
    {
        "id": "regime_shift",
        "name": "AIAE Regime 切换",
        "check": lambda s: s.get("_regime_shifted", False),
        "value_key": "aiae_regime",
        "severity": "warning",
        "icon": "🔄",
        "title_tpl": "Regime 切换 → R{value:.0f}",
        "detail_tpl": "AIAE 市场温度 Regime 发生切换，当前 R{value:.0f}。建议审查仓位是否需要调整至新 Regime 对应水平。",
        "cooldown_hours": 24,
    },
    {
        "id": "tail_risk_high",
        "name": "尾部风险过高",
        "check": lambda s: (s.get("tail_risk_score") or 0) >= 60,
        "value_key": "tail_risk_score",
        "severity": "critical",
        "icon": "🔥",
        "title_tpl": "尾部风险 {value:.0f} (≥60 危险)",
        "detail_tpl": "综合集中度/VIX/AIAE 信号，尾部风险评分 {value:.0f}，处于危险区间。建议：降仓至70%建议水平 + 严格止损。",
        "cooldown_hours": 8,
    },
]


# ═══════════════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════════════

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "alert_config.json"
)

def _load_config() -> dict:
    """加载推送渠道配置"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"channels_enabled": ["browser"]}


# ═══════════════════════════════════════════════════
#  核心扫描逻辑
# ═══════════════════════════════════════════════════

def scan_and_alert() -> list:
    """
    扫描所有规则, 返回本次触发的预警列表。
    由 warmup_pipeline / dashboard_builder 调用。
    """
    from services import db as ac_db
    from dashboard_modules.decision_engine import _build_snapshot_from_cache, compute_jcs

    # 1. 构建快照
    snapshot = _build_snapshot_from_cache()
    if not snapshot:
        return []

    # 2. 计算 JCS
    jcs = compute_jcs(snapshot)
    snapshot["jcs_score"] = jcs["score"]
    snapshot["jcs_level"] = jcs["level"]
    snapshot["pos"] = snapshot.get("suggested_position", "?")

    # P4: Regime 切换检测 — 对比上一次决策记录
    try:
        history = ac_db.get_decision_history(2)
        if len(history) >= 2:
            prev_regime = history[-2].get("aiae_regime")
            curr_regime = snapshot.get("aiae_regime")
            if prev_regime is not None and curr_regime is not None and prev_regime != curr_regime:
                snapshot["_regime_shifted"] = True
    except Exception:
        pass

    # P4: 尾部风险注入
    try:
        from dashboard_modules.decision_engine import compute_risk_matrix
        risk = compute_risk_matrix()
        snapshot["tail_risk_score"] = risk.get("tail_risk", {}).get("score", 0)
    except Exception:
        pass

    # 3. 遍历规则
    triggered = []
    for rule in ALERT_RULES:
        if not rule["check"](snapshot):
            continue

        # Cooldown 检查 (P2-1: 健壮时间解析, 兼容 ±时区/微秒/纯日期)
        last_time_str = ac_db.get_last_alert_time(rule["id"])
        if last_time_str:
            try:
                # 尝试标准 ISO 解析, 失败时截断时区后缀重试
                try:
                    last_time = datetime.fromisoformat(last_time_str)
                except ValueError:
                    # 兼容 Python <3.11: 截断 +08:00 等时区后缀
                    clean = last_time_str[:19]  # 取 YYYY-MM-DDTHH:MM:SS
                    last_time = datetime.fromisoformat(clean)
                cooldown = timedelta(hours=rule["cooldown_hours"])
                if datetime.now() - last_time < cooldown:
                    logger.debug("预警抑制 [%s]: cooldown %dh 内已触发", rule["id"], rule["cooldown_hours"])
                    continue
            except (ValueError, TypeError):
                pass  # 时间解析彻底失败, 不抑制 (保守策略: 宁可多报不漏报)

        # 触发! 生成预警内容
        value = snapshot.get(rule["value_key"], 0) or 0
        title = rule["title_tpl"].format(value=value)
        detail = rule["detail_tpl"].format(value=value, pos=snapshot.get("pos", "?"))

        # 写入 SQLite
        ac_db.save_alert(
            rule_id=rule["id"],
            severity=rule["severity"],
            title=f'{rule["icon"]} {title}',
            detail=detail,
            value=value,
        )

        alert_info = {
            "rule_id": rule["id"],
            "severity": rule["severity"],
            "icon": rule["icon"],
            "title": title,
            "detail": detail,
            "value": value,
        }
        triggered.append(alert_info)
        logger.info("🔔 预警触发 [%s]: %s (value=%.2f)", rule["id"], title, value)

    # 4. 多渠道推送 (异步, 不阻塞主流程)
    if triggered:
        threading.Thread(target=_push_all_channels, args=(triggered,), daemon=True).start()

    return triggered


# ═══════════════════════════════════════════════════
#  多渠道推送
# ═══════════════════════════════════════════════════

def _push_all_channels(alerts: list):
    """推送到所有启用的渠道"""
    config = _load_config()
    channels = config.get("channels_enabled", ["browser"])

    for alert in alerts:
        title = f'{alert["icon"]} {alert["title"]}'
        body = alert["detail"]

        if "serverchan" in channels:
            _push_serverchan(config.get("serverchan_sendkey", ""), title, body)

        if "email" in channels:
            _push_email(config.get("email_smtp", {}), title, body)

        if "wecom" in channels:
            _push_wecom(config.get("wecom_webhook_url", ""), title, body)


def _push_serverchan(sendkey: str, title: str, body: str):
    """Server酱 → 微信推送"""
    if not sendkey:
        logger.warning("Server酱 SendKey 未配置, 跳过微信推送")
        return
    try:
        import urllib.request
        import urllib.parse
        url = f"https://sctapi.ftqq.com/{sendkey}.send"
        data = urllib.parse.urlencode({
            "title": title[:64],  # Server酱标题限制 64 字
            "desp": body,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("code") == 0:
                logger.info("✅ Server酱推送成功")
            else:
                logger.warning("Server酱推送失败: %s", result.get("message", "unknown"))
    except Exception as e:
        logger.warning("Server酱推送异常: %s", e)


def _push_email(smtp_config: dict, title: str, body: str):
    """QQ 邮箱 SMTP 推送"""
    host = smtp_config.get("host")
    user = smtp_config.get("user")
    password = smtp_config.get("password")
    to_addr = smtp_config.get("to", user)

    if not all([host, user, password]):
        logger.warning("邮件 SMTP 配置不完整, 跳过邮件推送")
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = f"AlphaCore Alert <{user}>"
        msg["To"] = to_addr
        msg["Subject"] = Header(f"[AlphaCore] {title}", "utf-8")

        port = smtp_config.get("port", 465)
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
        server.quit()
        logger.info("✅ 邮件推送成功 → %s", to_addr)
    except Exception as e:
        logger.warning("邮件推送异常: %s", e)


def _push_wecom(webhook_url: str, title: str, body: str):
    """P4: 企业微信 Webhook 推送 (零审核, Markdown 格式)"""
    if not webhook_url:
        logger.warning("企业微信 Webhook URL 未配置, 跳过推送")
        return
    try:
        import urllib.request
        from version import VERSION_STRING
        md_content = (
            f"## {title}\n\n"
            f"{body}\n\n"
            f"> {VERSION_STRING} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": md_content}
        }).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("errcode") == 0:
                logger.info("✅ 企业微信推送成功")
            else:
                logger.warning("企业微信推送失败: %s", result.get("errmsg", "unknown"))
    except Exception as e:
        logger.warning("企业微信推送异常: %s", e)
