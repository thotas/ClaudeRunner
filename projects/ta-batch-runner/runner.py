#!/usr/bin/env python3
"""
TradingAgents Batch Runner — Sequential multi-ticker runner.

Reads tickers from config.json, runs TA analysis for each ticker sequentially,
uploads reports to GCP VM (thotas@34.82.106.90:/var/www/static/), tracks state
in ~/.hermes/ta-batch-state.json, and sends Telegram alerts on completion.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    with open(config_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

@dataclass
class TickerResult:
    ticker: str
    status: str  # pending | running | completed | failed | skipped
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    rating: Optional[str] = None
    error: Optional[str] = None
    report_url: Optional[str] = None


@dataclass
class BatchState:
    batch_id: str
    started_at: str
    completed_at: Optional[str] = None
    status: str = "running"  # running | completed | failed
    tickers: list[TickerResult] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BatchState":
        d["tickers"] = [TickerResult(**t) for t in d.get("tickers", [])]
        return cls(**d)


def load_state(state_file: Path) -> Optional[BatchState]:
    if not state_file.exists():
        return None
    with open(state_file) as f:
        return BatchState.from_dict(json.load(f))


def save_state(state: BatchState, state_file: Path):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state.to_dict(), f, indent=2)


# ---------------------------------------------------------------------------
# Telegram alerts
# ---------------------------------------------------------------------------

def send_telegram_message(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: str = "7192357563",
) -> bool:
    """Send a Telegram message via bot API."""
    if bot_token is None:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("  [WARN] TELEGRAM_BOT_TOKEN not set, skipping Telegram alert")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [WARN] Telegram send failed: {e}")
        return False


def send_telegram_document(
    file_path: Path,
    caption: str,
    bot_token: Optional[str] = None,
    chat_id: str = "7192357563",
) -> bool:
    """Send a document (zip) to Telegram."""
    if bot_token is None:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("  [WARN] TELEGRAM_BOT_TOKEN not set, skipping document send")
        return False
    try:
        with open(file_path, "rb") as f:
            files = {"document": (file_path.name, f)}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            resp = httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data=data,
                files=files,
                timeout=60,
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [WARN] Telegram document send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# GCP upload
# ---------------------------------------------------------------------------

def gcp_upload_report(
    html_file: Path,
    ticker: str,
    gcp_host: str,
    remote_base: str,
    local_tmp: Path,
) -> Optional[str]:
    """
    SCP report.html to GCP VM, then sudo mv to /var/www/static/{ticker}-trading-report.html.
    Returns the public URL on success.
    """
    remote_file = f"{gcp_host}:/home/thotas/{ticker}-trading-report.html"
    remote_final = f"{gcp_host}:/var/www/static/{ticker}-trading-report.html"

    # SCP to staging area on VM
    scp_cmd = [
        "scp", "-o", "StrictHostKeyChecking=no",
        str(html_file),
        remote_file,
    ]
    result = subprocess.run(scp_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] SCP failed: {result.stderr}")
        return None

    # sudo mv to static directory
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        gcp_host,
        f"sudo mv /home/thotas/{ticker}-trading-report.html /var/www/static/ && echo OK",
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True)
    if result.returncode != 0 or "OK" not in result.stdout:
        print(f"  [ERROR] SSH sudo mv failed: {result.stderr}")
        return None

    return f"https://babu.thotas.com/{ticker}-trading-report.html"


def verify_report_url(url: str) -> bool:
    """Check that the uploaded report returns HTTP 200."""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# TradingAgents analysis
# ---------------------------------------------------------------------------

def get_today() -> str:
    return date.today().isoformat()


def swap_ticker_in_script(script_path: Path, ticker: str) -> bool:
    """Replace TICKER value in run_analysis.py."""
    content = script_path.read_text()
    new_content = re.sub(
        r'^TICKER = "[^"]*"',
        f'TICKER = "{ticker}"',
        content,
        flags=re.MULTILINE,
    )
    if new_content == content:
        print(f"  [WARN] TICKER swap had no effect — pattern may have changed")
    script_path.write_text(new_content)
    return True


def run_ta_analysis(
    ta_dir: Path,
    venv_activate: str,
    script_path: Path,
    ticker: str,
    timeout: int = 900,
) -> subprocess.CompletedProcess:
    """
    Run TradingAgents analysis for one ticker.
    Swaps the ticker, activates venv, runs the script.
    """
    swap_ticker_in_script(script_path, ticker)

    cmd = f'''
        cd {ta_dir} && \\
        source {venv_activate} && \\
        source .env && \\
        python run_analysis.py 2>&1
    '''
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def generate_report_html(
    state_file: Path,
    ticker: str,
    today: str,
    report_script: Path,
) -> Optional[Path]:
    """
    Generate report.html from full_state.json using the standalone generator.
    Returns the path to the generated report.html.
    """
    if not state_file.exists():
        print(f"  [ERROR] full_state.json not found: {state_file}")
        return None

    out_dir = state_file.parent
    gen_script = Path(report_script).expanduser()

    # Build the generation command
    cmd = [
        sys.executable, str(gen_script),
        "--ticker", ticker,
        "--date", today,
        "--output-dir", str(out_dir),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  [WARN] gen_ticker_report.py failed: {result.stderr}")
        # Fall back to inline generation
        return _generate_report_inline(state_file, ticker, today, out_dir)
    else:
        html_file = out_dir / "report.html"
        if html_file.exists():
            return html_file
        return _generate_report_inline(state_file, ticker, today, out_dir)


def _generate_report_inline(
    state_file: Path,
    ticker: str,
    today: str,
    out_dir: Path,
) -> Path:
    """
    Inline HTML report generator — used as fallback when gen_ticker_report.py
    is unavailable or fails.
    """
    import html as html_lib

    data = json.loads(state_file.read_text())

    def esc(s):
        if s is None:
            return ""
        s = str(s)
        s = html_lib.escape(s, quote=True)
        s = s.replace("`", "&#96;").replace("${", "&#36;{")
        return s

    def md(text):
        if not text:
            return ""
        text = text.strip()
        text = re.sub(r"```([\s\S]*?)```", r"<pre><code>\1</code></pre>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"^###### (.+)$", r"<h6>\1</h6>", text, flags=re.MULTILINE)
        text = re.sub(r"^##### (.+)$", r"<h5>\1</h5>", text, flags=re.MULTILINE)
        text = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", text, flags=re.MULTILINE)
        text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
        text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
        text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        text = re.sub(r"^---$", r"<hr>", text, flags=re.MULTILINE)
        text = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\. (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
        text = re.sub(r"\n\n+", "</p><p>", text)
        return f"<p>{text}</p>"

    # Extract rating
    rating = "Hold"
    ftd = data.get("final_trade_decision", "")
    for line in ftd.strip().split("\n"):
        if "Rating" in line:
            rating = line.split(":", 1)[-1].strip().replace("**", "").replace("*", "").strip()
            break

    rl = rating.lower()
    if "overweight" in rl or "buy" in rl or "bullish" in rl:
        badge_color = "var(--success)"
    elif "underweight" in rl or "sell" in rl or "bearish" in rl:
        badge_color = "var(--danger)"
    else:
        badge_color = "var(--warning)"

    fields = {
        "summary": data.get("investment_plan", ""),
        "technical": data.get("market_report", ""),
        "fundamental": data.get("fundamentals_report", ""),
        "news": data.get("news_report", ""),
        "bull": data.get("investment_debate_state", {}).get("bull_history", ""),
        "bear": data.get("investment_debate_state", {}).get("bear_history", ""),
        "aggressive": data.get("risk_debate_state", {}).get("aggressive_history", ""),
        "conservative": data.get("risk_debate_state", {}).get("conservative_history", ""),
        "neutral": data.get("risk_debate_state", {}).get("neutral_history", ""),
        "decision": ftd,
        "trader": data.get("trader_investment_plan", ""),
    }

    tabs = [
        ("Summary", "summary"),
        ("Technical", "technical"),
        ("Fundamental", "fundamental"),
        ("News", "news"),
        ("Bull", "bull"),
        ("Bear", "bear"),
        ("Aggressive", "aggressive"),
        ("Conservative", "conservative"),
        ("Neutral", "neutral"),
        ("Decision", "decision"),
        ("Trader", "trader"),
    ]

    data_escaped = {}
    for key, val in fields.items():
        data_escaped[key] = esc(val)
    data_json = json.dumps(data_escaped, indent=None)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ticker} — Trading Analysis Report</title>
<style>
:root {{
  --bg: #ffffff; --surface: #f8fafc; --border: #e2e8f0;
  --text: #1e293b; --muted: #64748b;
  --accent: #0ea5e9; --accent-dark: #0284c7;
  --success: #10b981; --warning: #f59e0b; --danger: #ef4444; --navy: #0f172a;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 16px; line-height: 1.6; background: var(--bg); color: var(--text); }}
.hero {{ background: var(--navy); color: #fff; padding: 32px 24px; text-align: center; }}
.hero h1 {{ font-size: 2.4em; letter-spacing: 0.05em; margin-bottom: 8px; }}
.hero .badge {{ display: inline-block; background: {badge_color}; color: #fff; font-weight: 700; font-size: 1.1em; padding: 6px 20px; border-radius: 24px; margin-top: 8px; }}
.hero .date {{ color: #94a3b8; margin-top: 8px; font-size: 0.95em; }}
.agent-bar {{ background: #1e293b; color: #94a3b8; padding: 10px 24px; font-size: 0.85em; overflow-x: auto; white-space: nowrap; }}
.agent-bar span {{ margin-right: 20px; }}
.agent-bar span b {{ color: #e2e8f0; }}
.tab-nav {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; display: flex; flex-wrap: wrap; gap: 2px; }}
.tab-nav button {{ background: none; border: none; padding: 12px 14px; font-size: 0.9em; font-weight: 600; color: var(--muted); cursor: pointer; border-bottom: 3px solid transparent; transition: color 0.2s, border-color 0.2s; }}
.tab-nav button:hover {{ color: var(--text); }}
.tab-nav button.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.tab-content {{ padding: 24px; max-width: 900px; margin: 0 auto; }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 20px; }}
.md-content {{ font-size: 0.95em; }}
.md-content h1 {{ font-size: 1.5em; margin: 1.2em 0 0.5em; color: var(--navy); }}
.md-content h2 {{ font-size: 1.25em; margin: 1em 0 0.4em; color: var(--navy); }}
.md-content h3 {{ font-size: 1.1em; margin: 0.9em 0 0.4em; color: var(--text); }}
.md-content h4,.md-content h5,.md-content h6 {{ font-size: 1em; margin: 0.8em 0 0.3em; }}
.md-content p {{ margin: 0.6em 0; }}
.md-content ul,.md-content ol {{ margin: 0.5em 0 0.5em 1.5em; }}
.md-content li {{ margin: 0.25em 0; }}
.md-content table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.9em; overflow-x: auto; display: block; }}
.md-content th {{ background: var(--navy); color: #fff; padding: 8px 12px; text-align: left; }}
.md-content td {{ padding: 7px 12px; border: 1px solid var(--border); }}
.md-content tr:nth-child(even) td {{ background: var(--surface); }}
.md-content code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.88em; }}
.md-content pre {{ background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 8px; overflow-x: auto; margin: 1em 0; }}
.md-content pre code {{ background: none; padding: 0; color: inherit; }}
.md-content hr {{ border: none; border-top: 2px solid var(--border); margin: 1.5em 0; }}
.ft {{ text-align: center; padding: 24px; color: var(--muted); font-size: 0.85em; border-top: 1px solid var(--border); margin-top: 32px; }}
</style>
</head>
<body>
<div class="hero"><h1>{ticker}</h1><div class="badge">{esc(rating)}</div><div class="date">{today}</div></div>
<div class="agent-bar">
  <span><b>Agents:</b></span><span>📊 Market Analyst</span><span>📰 News Analyst</span><span>📈 Fundamental Analyst</span>
  <span>🐂 Bull Analyst</span><span>🐻 Bear Analyst</span><span>⚡ Aggressive Analyst</span>
  <span>🛡️ Conservative Analyst</span><span>⚖️ Neutral Analyst</span><span>🤖 Judge</span><span>💼 Trader</span>
</div>
<div class="tab-nav">
  <button class="active" onclick="show('summary')">Summary</button>
  <button onclick="show('technical')">Technical</button>
  <button onclick="show('fundamental')">Fundamental</button>
  <button onclick="show('news')">News</button>
  <button onclick="show('bull')">Bull</button>
  <button onclick="show('bear')">Bear</button>
  <button onclick="show('aggressive')">Aggressive</button>
  <button onclick="show('conservative')">Conservative</button>
  <button onclick="show('neutral')">Neutral</button>
  <button onclick="show('decision')">Decision</button>
  <button onclick="show('trader')">Trader</button>
</div>
<div class="tab-content">
  <div id="tab-summary" class="tab-panel active"></div>
  <div id="tab-technical" class="tab-panel"></div>
  <div id="tab-fundamental" class="tab-panel"></div>
  <div id="tab-news" class="tab-panel"></div>
  <div id="tab-bull" class="tab-panel"></div>
  <div id="tab-bear" class="tab-panel"></div>
  <div id="tab-aggressive" class="tab-panel"></div>
  <div id="tab-conservative" class="tab-panel"></div>
  <div id="tab-neutral" class="tab-panel"></div>
  <div id="tab-decision" class="tab-panel"></div>
  <div id="tab-trader" class="tab-panel"></div>
</div>
<div class="ft">Generated by TradingAgents · {today}</div>
<script>
const DATA = {data_json};
function md(text) {{
  if (!text) return '';
  text = text.replace(/&lt;h([1-6])&gt;/g, function(m, n) {{ return '<h' + n + '>'; }});
  text = text.replace(/&lt;\/h([1-6])&gt;/g, function(m, n) {{ return '</h' + n + '>'; }});
  text = text.replace(/&lt;pre&gt;/g, '<pre>').replace(/&lt;\/pre&gt;/g, '</pre>');
  text = text.replace(/&lt;code&gt;/g, '<code>').replace(/&lt;\/code&gt;/g, '</code>');
  text = text.replace(/&lt;hr&gt;/g, '<hr>');
  text = text.replace(/&lt;li&gt;/g, '<li>').replace(/&lt;\/li&gt;/g, '</li>');
  return text;
}}
function show(id) {{
  document.querySelectorAll('.tab-nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  if (event && event.target) event.target.classList.add('active');
}}
function populate(id, text) {{
  const el = document.getElementById('tab-'+id);
  if (el) el.innerHTML = '<div class="card"><div class="md-content">' + md(text) + '</div></div>';
}}
document.addEventListener('DOMContentLoaded', function() {{
  populate('summary', DATA.summary); populate('technical', DATA.technical);
  populate('fundamental', DATA.fundamental); populate('news', DATA.news);
  populate('bull', DATA.bull); populate('bear', DATA.bear);
  populate('aggressive', DATA.aggressive); populate('conservative', DATA.conservative);
  populate('neutral', DATA.neutral); populate('decision', DATA.decision);
  populate('trader', DATA.trader);
}});
</script>
</body>
</html>"""

    html_file = out_dir / "report.html"
    with open(html_file, "w") as f:
        f.write(html)
    return html_file


def find_full_state(ticker: str, today: str, ta_dir: Path) -> Optional[Path]:
    """Locate full_state.json for a completed run."""
    candidates = [
        ta_dir / "outputs" / ticker / today / "full_state.json",
        ta_dir / "outputs" / ticker / "full_state.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Search by most recent date dir
    output_dir = ta_dir / "outputs" / ticker
    if output_dir.exists():
        date_dirs = sorted(output_dir.iterdir(), reverse=True)
        for d in date_dirs:
            p = d / "full_state.json"
            if p.exists():
                return p
    return None


def extract_rating(full_state: Path) -> str:
    """Extract rating string from full_state.json."""
    try:
        data = json.loads(full_state.read_text())
        ftd = data.get("final_trade_decision", "")
        for line in ftd.strip().split("\n"):
            if "Rating" in line:
                return line.split(":", 1)[-1].strip().replace("**", "").replace("*", "").strip()
    except Exception:
        pass
    return "Hold"


def zip_report_files(html_file: Path, data_file: Path, state_file: Path, ticker: str, today: str) -> Path:
    """Create a zip of report artifacts."""
    zip_path = Path(f"/tmp/{ticker.lower()}_report_{today}.zip")
    subprocess.run(
        ["zip", "-j", str(zip_path), str(html_file), str(data_file), str(state_file)],
        check=True,
        capture_output=True,
    )
    return zip_path


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(config: dict, dry_run: bool = False) -> BatchState:
    """Execute the full batch run."""
    tickers = config["tickers"]
    ta_dir = Path(config["ta_dir"])
    venv_activate = config["venv_activate"]
    script_path = Path(config["run_analysis_script"])
    state_file = Path(config["state_file"])
    log_dir = Path(config.get("log_dir", "/Users/babu/Development/ClaudeRunner/logs/ta-batch"))
    gcp_config = config.get("gcp_vm", {})
    telegram_config = config.get("telegram", {})
    timeout = config.get("analysis_timeout_seconds", 900)
    report_script = Path(config.get("report_script", ""))

    today = get_today()
    import uuid
    batch_id = f"batch-{today}-{uuid.uuid4().hex[:8]}"

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{batch_id}.log"

    state = BatchState(
        batch_id=batch_id,
        started_at=datetime.now().isoformat(),
        tickers=[TickerResult(ticker=t, status="pending") for t in tickers],
    )
    save_state(state, state_file)

    print(f"[{batch_id}] Batch started — {len(tickers)} tickers: {tickers}")
    print(f"  Log: {log_file}")
    print(f"  State: {state_file}")

    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        with open(log_file, "a") as f:
            f.write(line + "\n")

    def update_ticker(idx: int, **kwargs):
        for k, v in kwargs.items():
            setattr(state.tickers[idx], k, v)
        save_state(state, state_file)

    try:
        for idx, ticker in enumerate(tickers):
            log(f"=== {ticker} ({idx + 1}/{len(tickers)}) ===")
            update_ticker(idx, status="running", started_at=datetime.now().isoformat())

            if dry_run:
                log(f"[DRY RUN] Skipping analysis for {ticker}")
                update_ticker(idx, status="completed", completed_at=datetime.now().isoformat(), rating="Hold")
                continue

            # Run analysis
            try:
                result = run_ta_analysis(
                    ta_dir=ta_dir,
                    venv_activate=venv_activate,
                    script_path=script_path,
                    ticker=ticker,
                    timeout=timeout,
                )
                if result.returncode != 0:
                    log(f"[ERROR] Analysis failed for {ticker}: {result.stderr[-500:]}")
                    update_ticker(idx, status="failed", completed_at=datetime.now().isoformat(),
                                  error=result.stderr[-300:])
                    continue
            except subprocess.TimeoutExpired:
                log(f"[ERROR] Analysis timed out for {ticker} after {timeout}s")
                update_ticker(idx, status="failed", completed_at=datetime.now().isoformat(),
                              error=f"Timeout after {timeout}s")
                continue
            except Exception as e:
                log(f"[ERROR] Analysis exception for {ticker}: {e}")
                update_ticker(idx, status="failed", completed_at=datetime.now().isoformat(), error=str(e))
                continue

            # Find full_state
            full_state = find_full_state(ticker, today, ta_dir)
            if full_state is None:
                log(f"[ERROR] full_state.json not found for {ticker}")
                update_ticker(idx, status="failed", completed_at=datetime.now().isoformat(),
                              error="full_state.json not found")
                continue

            # Extract rating
            rating = extract_rating(full_state)
            log(f"  Rating: {rating}")

            # Generate HTML report
            data_file = full_state.parent / "report_data.json"
            html_file = generate_report_html(full_state, ticker, today, report_script)
            if html_file is None or not html_file.exists():
                log(f"[WARN] Could not generate HTML, using inline generator")
                html_file = _generate_report_inline(full_state, ticker, today, full_state.parent)

            # Save data file
            data = json.loads(full_state.read_text())
            fields = {
                "investment_plan": data.get("investment_plan", ""),
                "market_report": data.get("market_report", ""),
                "fundamentals_report": data.get("fundamentals_report", ""),
                "news_report": data.get("news_report", ""),
                "bull_history": data.get("investment_debate_state", {}).get("bull_history", ""),
                "bear_history": data.get("investment_debate_state", {}).get("bear_history", ""),
                "aggressive_history": data.get("risk_debate_state", {}).get("aggressive_history", ""),
                "conservative_history": data.get("risk_debate_state", {}).get("conservative_history", ""),
                "neutral_history": data.get("risk_debate_state", {}).get("neutral_history", ""),
                "final_trade_decision": data.get("final_trade_decision", ""),
                "trader_investment_plan": data.get("trader_investment_plan", ""),
            }
            with open(data_file, "w") as f:
                json.dump(fields, f, indent=2)

            # GCP upload
            report_url = None
            if gcp_config:
                log(f"  Uploading report to GCP...")
                host = gcp_config.get("host", "thotas@34.82.106.90")
                remote_path = gcp_config.get("remote_path", "/var/www/static")
                local_tmp = Path(gcp_config.get("local_tmp_dir", "/tmp/ta-batch-gcp"))
                report_url = gcp_upload_report(html_file, ticker, host, remote_path, local_tmp)
                if report_url:
                    log(f"  Report URL: {report_url}")
                    verified = verify_report_url(report_url)
                    log(f"  URL verified: {verified}")
                else:
                    log(f"[WARN] GCP upload failed")

            # Telegram zip
            zip_path = zip_report_files(html_file, data_file, full_state, ticker, today)
            caption = f"{ticker} Trading Analysis — {today}\nRating: {rating}"
            send_telegram_document(zip_path, caption, chat_id=telegram_config.get("chat_id", "7192357563"))

            update_ticker(idx, status="completed", completed_at=datetime.now().isoformat(),
                          rating=rating, report_url=report_url)
            log(f"  {ticker} completed — {rating}")

        state.status = "completed"
        state.completed_at = datetime.now().isoformat()
        save_state(state, state_file)

        # Final Telegram summary
        completed = [t for t in state.tickers if t.status == "completed"]
        failed = [t for t in state.tickers if t.status == "failed"]
        summary = (
            f"📊 <b>Batch Complete</b> — {today}\n\n"
            f"✅ Completed ({len(completed)}): {', '.join(t.ticker for t in completed) if completed else 'none'}\n"
            f"❌ Failed ({len(failed)}): {', '.join(t.ticker for t in failed) if failed else 'none'}"
        )
        send_telegram_message(summary, chat_id=telegram_config.get("chat_id", "7192357563"))

        log(f"Batch complete — {len(completed)}/{len(tickers)} successful")

    except Exception as e:
        state.status = "failed"
        state.error = str(e)
        state.completed_at = datetime.now().isoformat()
        save_state(state, state_file)
        log(f"[FATAL] Batch failed: {e}")
        raise

    return state


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TradingAgents Batch Runner")
    parser.add_argument("--config", "-c", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Skip analysis, test state tracking only")
    args = parser.parse_args()

    config = load_config(args.config)
    state = run_batch(config, dry_run=args.dry_run)

    # Print summary
    print("\n=== Batch Summary ===")
    for t in state.tickers:
        status_icon = {"completed": "✅", "failed": "❌", "running": "⏳", "pending": "⏸"}.get(t.status, "?")
        print(f"  {status_icon} {t.ticker}: {t.status} | {t.rating or '—'} | {t.report_url or '—'}")

    sys.exit(0 if state.status == "completed" else 1)


if __name__ == "__main__":
    main()
