#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lê monitor.yml, baixa as páginas, verifica palavras-chave de abertura/bloqueio,
faz dedupe por X dias e gera um corpo de e-mail em HTML/Markdown.

Requer: PyYAML (instalado no workflow)
"""

import os, re, sys, json, time, html
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    import yaml  # PyYAML
except Exception as e:
    print("Faltando PyYAML. Instale com 'pip install pyyaml'.", file=sys.stderr)
    sys.exit(2)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0 Safari/537.36")

def fetch(url: str, timeout=30) -> str:
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # Tentativa de decodificação com fallback
            for enc in ("utf-8", "latin-1"):
                try:
                    return data.decode(enc, errors="ignore")
                except Exception:
                    continue
            return data.decode(errors="ignore")
    except HTTPError as e:
        return f"__HTTP_ERROR__ {e.code}"
    except URLError as e:
        return f"__URL_ERROR__ {e.reason}"
    except Exception as e:
        return f"__GENERIC_ERROR__ {e}"

def norm(s: str) -> str:
    # lowercase, collapse spaces
    return re.sub(r"\s+", " ", s.lower()).strip()

def find_any(text: str, patterns):
    t = norm(text)
    for p in patterns:
        if re.search(p if p.startswith("(?i)") else re.escape(p), t, flags=0):
            return True
    return False

def detect_dates_2026(text: str, locale: str):
    """
    (Opcional) Tenta encontrar datas explícitas de 2026.
    Retorna lista de strings de datas encontradas.
    """
    t = text
    months_es = r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    months_en = r"january|february|march|april|may|june|july|august|september|october|november|december"
    months = months_es if locale.startswith("es") else months_en
    # Exemplos: "5 septiembre 2026", "September 5, 2026", "05/09/2026"
    rx = re.compile(
        rf"(\b\d{{1,2}}\s+(?:{months})\s+2026\b|\b(?:{months})\s+\d{{1,2}},?\s+2026\b|\b\d{{1,2}}[/-]\d{{1,2}}[/-]2026\b)",
        re.IGNORECASE
    )
    return list(set(m.group(0) for m in rx.finditer(t)))

def load_config(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state(path: str):
    if not os.path.exists(path):
        return {"alerts": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"alerts": []}

def save_state(path: str, state: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def within_days(ts_iso: str, days: int) -> bool:
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts < timedelta(days=days)
    except Exception:
        return False

def main():
    cfg_path = os.environ.get("MONITOR_CONFIG", "monitor.yml")
    state_path = os.environ.get("STATE_PATH", ".state/state.json")
    out_html = os.environ.get("OUT_HTML", "alerts.html")
    out_md = os.environ.get("OUT_MD", "alerts.md")

    cfg = load_config(cfg_path)
    window_days = int(cfg.get("window_days", 45))
    dedupe_days = int(cfg.get("dedupe_days", 7))
    events = cfg.get("events", [])

    state = load_state(state_path)
    prev_alerts = state.get("alerts", [])

    new_alerts = []
    details = []

    for ev in events:
        name = ev["name"]
        urls = ev.get("urls", [])
        locale = ev.get("locale", "en")
        kw_any = [k.lower() for k in ev.get("keywords_any", [])]
        kw_block = [k.lower() for k in ev.get("keywords_block", [])]

        for url in urls:
            html_text = fetch(url)
            if html_text.startswith("__"):
                # erro de rede/HTTP
                details.append(f"- {name} — {url}: erro ao buscar ({html_text})")
                continue

            # Heurística: se houver algum termo de abertura e NENHUM termo de bloqueio, consideramos "aberto"
            opened = find_any(html_text, kw_any) and not find_any(html_text, kw_block)

            # (Opcional) datas explícitas 2026 (útil se quiser usar window_days no futuro)
            found_dates = detect_dates_2026(html_text, locale)
            found_dates_txt = (", ".join(found_dates)) if found_dates else "nenhuma"

            if opened:
                reason = f"{name} — inscrições possivelmente abertas em {url}"
                # dedupe: se já alertamos por esse mesmo motivo/url recentemente, pule
                key = {"reason": reason, "url": url, "event": name}
                duplicate = False
                for a in prev_alerts:
                    if a.get("event") == name and a.get("url") == url and a.get("reason") == reason:
                        if within_days(a.get("ts", ""), dedupe_days):
                            duplicate = True
                            break
                if not duplicate:
                    new_alerts.append({
                        "event": name,
                        "url": url,
                        "reason": reason,
                        "dates_2026": found_dates,
                        "ts": datetime.now(timezone.utc).isoformat()
                    })
                details.append(f"- {name} — {url}: ABERTO? ✅ | datas 2026 detectadas: {found_dates_txt}")
            else:
                # Não abriu (ou bloqueado por termos como “closed”, “will open”, etc.)
                details.append(f"- {name} — {url}: aberto? ❌ | datas 2026: {found_dates_txt}")

    # Atualiza estado (append) e limita histórico
    if new_alerts:
        prev_alerts.extend(new_alerts)
        # Limpa histórico antigo (> 180 dias) para não crescer indefinidamente
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)
        prev_alerts = [a for a in prev_alerts
                       if datetime.fromisoformat(a["ts"].replace("Z", "+00:00")) >= cutoff]
        state["alerts"] = prev_alerts
        save_state(state_path, state)

    # Monta saídas
    triggered = bool(new_alerts)

    def html_escape(s): return html.escape(s)

    html_body = [
        "<h2>Monitor de Inscrições 2026 – Resultado</h2>",
        f"<p><strong>Execução:</strong> {datetime.now().isoformat(timespec='seconds')}</p>",
        "<h3>Status por página</h3>",
        "<ul>",
    ]
    for d in details:
        html_body.append(f"<li>{html_escape(d)}</li>")
    html_body.append("</ul>")

    if triggered:
        html_body.append("<hr><h3>🎯 NOVOS ALERTAS</h3><ul>")
        for a in new_alerts:
            html_body.append(
                f"<li><strong>{html_escape(a['event'])}</strong>: {html_escape(a['reason'])} — "
                f"{a[{html_escape(a['url'])}</a></li>"
            )
        html_body.append("</ul>")
    else:
        html_body.append("<p>Nenhum novo alerta nesta execução.</p>")

    html_content = "\n".join(html_body)

    md_content = "## Monitor de Inscrições 2026 – Resultado\n\n" + \
                 f"**Execução:** {datetime.now().isoformat(timespec='seconds')}\n\n" + \
                 "### Status por página\n" + "\n".join([f"- {d}" for d in details]) + "\n\n"
    if triggered:
        md_content += "### 🎯 Novos alertas\n" + "\n".join(
            [f"- **{a['event']}**: {a['reason']} — {a['url']}" for a in new_alerts]
        )
    else:
        md_content += "_Nenhum novo alerta nesta execução._\n"

    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html_content)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Sinaliza ao workflow
    print(json.dumps({
        "triggered": triggered,
        "new_alerts_count": len(new_alerts)
    }))

if __name__ == "__main__":
    main()
