#!/usr/bin/env python3
"""Relatório consolidado do pipeline de migração (3 fases).

Compara os relatórios de qualidade do DEST nas 3 etapas do pipeline:
  FASE 1 — PRÉ-LIMPEZA  (base restaurada, antes da limpeza de orphans)
  FASE 2 — PÓS-LIMPEZA  (após limpeza de orphans FK, antes da migração)
  FASE 3 — PÓS-MIGRAÇÃO (após execução de python -m src.migrar)

Uso:
  python3 scripts/reports/relatorio_consolidado_pipeline.py
  python3 scripts/reports/relatorio_consolidado_pipeline.py  \\
      tmp/relatorio_qualidade_dest_YYYYMMDD-HHMMSS.txt  \\
      tmp/relatorio_qualidade_dest_YYYYMMDD-HHMMSS.txt  \\
      tmp/relatorio_qualidade_dest_YYYYMMDD-HHMMSS.txt

Se os arquivos não forem passados, auto-detecta os 3 mais recentes
correspondentes ao padrão  tmp/relatorio_qualidade_dest_*.txt.
"""
from __future__ import annotations

import datetime
import io
import re
import sys
from pathlib import Path

# ── setup de path ────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent
TMP_DIR = ROOT / "tmp"

SEP = "=" * 76
SEP2 = "-" * 76
WIDTH_LABEL = 34
WIDTH_COL = 14


# ── parser de relatório ───────────────────────────────────────────────────────


def _int(s: str) -> int:
    """Converte string com vírgulas para int."""
    return int(s.replace(",", "").replace(".", "").strip())


def parse_report(path: Path) -> dict:
    """Extrai métricas-chave de um arquivo relatorio_qualidade_dest_*.txt."""
    text = path.read_text(encoding="utf-8", errors="replace")
    r: dict = {"file": path.name}

    # timestamp do relatório (cabeçalho ou resumo executivo)
    m = re.search(r"Gerado em:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    r["generated_at"] = m.group(1) if m else path.stem.split("_")[-1]

    # timestamp do arquivo → para ordenação
    m_ts = re.search(r"(\d{8}-\d{6})", path.name)
    r["file_ts"] = m_ts.group(1) if m_ts else path.stem

    # ── VOLUMES TOTAIS (do bloco 7 — resume DB real) ──────────────────────────
    # Linhas do estilo "  accounts                                 18"
    for key in ("accounts", "contacts", "conversations", "messages", "attachments", "inboxes"):
        m = re.search(rf"^\s+{key}\s+([\d,]+)\s*$", text, re.MULTILINE)
        r[key] = _int(m.group(1)) if m else None

    # Total accounts (fallback via BLOCO 1)
    if r.get("accounts") is None:
        m = re.search(r"Total accounts no DEST:\s+([\d,]+)", text)
        r["accounts"] = _int(m.group(1)) if m else None

    # ── FK VIOLATIONS ─────────────────────────────────────────────────────────
    m = re.search(r"Total de violações FK detectadas:\s+([\d,]+)", text)
    r["fk_total"] = _int(m.group(1)) if m else 0

    m = re.search(r"contacts sem account\s+([\d,]+)", text)
    r["fk_contacts"] = _int(m.group(1)) if m else 0

    m = re.search(r"conversations sem account\s+([\d,]+)", text)
    r["fk_conversations"] = _int(m.group(1)) if m else 0

    m = re.search(r"messages sem conversation\s+([\d,]+)", text)
    r["fk_messages"] = _int(m.group(1)) if m else 0

    # ── COBERTURA DA MIGRAÇÃO ─────────────────────────────────────────────────
    # "total registros rastreados                0"
    m = re.search(r"total registros rastreados\s+([\d,]+)", text)
    r["migration_tracked"] = _int(m.group(1)) if m else 0

    r["migration_state_missing"] = "migration_state não existe" in text

    # ── MIGRATION LOG TOTAIS (de bloco 3 tabela por tabela, se disponível) ────
    # Padrão: "contacts    id_destino  5966 migrated"  ←  do bloco_cobertura
    for tabela in ("accounts", "contacts", "conversations", "messages", "attachments"):
        m = re.search(
            rf"^\s+{tabela}\s+[\d,]+\s+([\d,]+)\s*$",
            text,
            re.MULTILINE,
        )
        r[f"mig_{tabela}"] = _int(m.group(1)) if m else None

    return r


# ── auto-detecção de arquivos ─────────────────────────────────────────────────


def autodetect_files() -> list[Path]:
    """Retorna os 3 mais recentes relatorio_qualidade_dest_*.txt em tmp/."""
    candidates = sorted(TMP_DIR.glob("relatorio_qualidade_dest_*.txt"))
    if len(candidates) < 3:
        return candidates
    return candidates[-3:]


# ── helpers de exibição ───────────────────────────────────────────────────────


def _fmt(v, delta: bool = False) -> str:
    if v is None:
        return "—"
    if delta:
        sign = "+" if v > 0 else ""
        return f"{sign}{v:,}"
    return f"{v:,}"


def _delta_pct(new: int | None, old: int | None) -> str:
    if new is None or old is None or old == 0:
        return ""
    pct = (new - old) / old * 100
    s = f"{pct:+.1f}%"
    return s


def row(label: str, p1, p2, p3, key: str, delta: bool = True) -> str:
    v1 = p1.get(key)
    v2 = p2.get(key)
    v3 = p3.get(key)
    dv = None
    if v1 is not None and v3 is not None:
        dv = v3 - v1
    dv_str = _fmt(dv, delta=True) if dv is not None else "—"
    return (
        f"  {label:<{WIDTH_LABEL}}"
        f"  {_fmt(v1):>{WIDTH_COL}}"
        f"  {_fmt(v2):>{WIDTH_COL}}"
        f"  {_fmt(v3):>{WIDTH_COL}}"
        f"  {dv_str:>{WIDTH_COL}}"
    )


def header_row() -> str:
    return (
        f"  {'MÉTRICA':<{WIDTH_LABEL}}"
        f"  {'FASE 1':>{WIDTH_COL}}"
        f"  {'FASE 2':>{WIDTH_COL}}"
        f"  {'FASE 3':>{WIDTH_COL}}"
        f"  {'DELTA (3-1)':>{WIDTH_COL}}"
    )


# ── geração do relatório ──────────────────────────────────────────────────────

_SEP3 = "\u2500" * (WIDTH_LABEL + 4 * (WIDTH_COL + 2))


def gerar_relatorio(p1: dict, p2: dict, p3: dict) -> str:
    buf = io.StringIO()

    def pr(*args, **kw):
        print(*args, file=buf, **kw)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pr()
    pr(SEP)
    pr("  RELATÓRIO CONSOLIDADO DO PIPELINE DE MIGRAÇÃO")
    pr(f"  Gerado em: {now}")
    pr(SEP)

    pr()
    pr(f"  {'FASE':<10}  {'ARQUIVO':<50}  GERADO EM")
    pr(f"  {'-'*10}  {'-'*50}  {'-'*20}")
    pr(f"  {'FASE 1':<10}  {p1['file']:<50}  {p1['generated_at']}")
    pr(f"  {'FASE 2':<10}  {p2['file']:<50}  {p2['generated_at']}")
    pr(f"  {'FASE 3':<10}  {p3['file']:<50}  {p3['generated_at']}")

    label_f1 = "PRÉ-LIMPEZA  (base restaurada)"
    label_f2 = "PÓS-LIMPEZA  (orphans removidos)"
    label_f3 = "PÓS-MIGRAÇÃO (migração executada)"
    pr()
    pr(f"  FASE 1 → {label_f1}")
    pr(f"  FASE 2 → {label_f2}")
    pr(f"  FASE 3 → {label_f3}")

    # ── VOLUMES TOTAIS ────────────────────────────────────────────────────────
    pr()
    pr(SEP)
    pr("  VOLUMES TOTAIS (todos os registros no banco DEST)")
    pr(SEP)
    pr()
    pr(header_row())
    pr(f"  {_SEP3}")
    pr(row("accounts", p1, p2, p3, "accounts"))
    pr(row("contacts", p1, p2, p3, "contacts"))
    pr(row("conversations", p1, p2, p3, "conversations"))
    pr(row("messages", p1, p2, p3, "messages"))
    pr(row("attachments", p1, p2, p3, "attachments"))
    pr(row("inboxes", p1, p2, p3, "inboxes"))

    # ── LIMPEZA: delta FASE 1 → FASE 2 ───────────────────────────────────────
    limpeza_contacts = (p1.get("contacts") or 0) - (p2.get("contacts") or 0)
    limpeza_convs = (p1.get("conversations") or 0) - (p2.get("conversations") or 0)
    limpeza_msgs = (p1.get("messages") or 0) - (p2.get("messages") or 0)
    limpeza_att = (p1.get("attachments") or 0) - (p2.get("attachments") or 0)
    pr()
    pr(SEP2)
    pr("  REGISTROS REMOVIDOS PELA LIMPEZA (FASE 1 − FASE 2)")
    pr(SEP2)
    pr(f"    contacts removidos (FK orphans) {limpeza_contacts:>12,}")
    pr(f"    conversations removidas         {limpeza_convs:>12,}")
    pr(f"    messages removidas              {limpeza_msgs:>12,}")
    pr(f"    attachments removidos           {limpeza_att:>12,}")

    # ── VOLUMES MIGRADOS (delta físico = FASE 3 − FASE 2, baseline pós-limpeza)
    contacts_added = (p3.get("contacts") or 0) - (p2.get("contacts") or 0)
    convers_added = (p3.get("conversations") or 0) - (p2.get("conversations") or 0)
    messages_added = (p3.get("messages") or 0) - (p2.get("messages") or 0)
    attach_added = (p3.get("attachments") or 0) - (p2.get("attachments") or 0)
    pr()
    pr(SEP2)
    pr("  REGISTROS ADICIONADOS PELA MIGRAÇÃO (FASE 3 − FASE 2, baseline pós-limpeza)")
    pr(SEP2)
    pr(
        f"    accounts inseridas              {(p3.get('accounts') or 0) - (p2.get('accounts') or 0):>12,}"
    )
    pr(f"    contacts inseridos              {contacts_added:>12,}")
    pr(f"    conversations inseridas         {convers_added:>12,}")
    pr(f"    messages inseridas              {messages_added:>12,}")
    pr(f"    attachments inseridos           {attach_added:>12,}")
    pr(
        f"    inboxes inseridos               {(p3.get('inboxes') or 0) - (p2.get('inboxes') or 0):>12,}"
    )

    # ── FK VIOLATIONS ─────────────────────────────────────────────────────────
    pr()
    pr(SEP)
    pr("  INTEGRIDADE REFERENCIAL (FK VIOLATIONS)")
    pr(SEP)
    pr()
    pr(header_row())
    pr(f"  {_SEP3}")
    pr(row("contacts sem account", p1, p2, p3, "fk_contacts"))
    pr(row("conversations sem account", p1, p2, p3, "fk_conversations"))
    pr(row("messages sem conversation", p1, p2, p3, "fk_messages"))
    pr(row("TOTAL FK violations", p1, p2, p3, "fk_total"))

    # ── COBERTURA MIGRAÇÃO ────────────────────────────────────────────────────
    pr()
    pr(SEP)
    pr("  COBERTURA DA MIGRAÇÃO (registros rastreados em migration_state)")
    pr(SEP)
    pr()
    pr(header_row())
    pr(f"  {_SEP3}")
    pr(row("total registros rastreados", p1, p2, p3, "migration_tracked"))

    if p1.get("migration_state_missing"):
        pr("  [FASE 1] migration_state não existia — base restaurada sem histórico.")
    if p2.get("migration_state_missing"):
        pr("  [FASE 2] migration_state não existia — base pós-limpeza sem histórico.")
    if p3.get("migration_state_missing"):
        pr("  [FASE 3] migration_state não existia — verificar saída da migração.")

    # ── AVALIAÇÃO ─────────────────────────────────────────────────────────────
    pr()
    pr(SEP)
    pr("  AVALIAÇÃO DO PIPELINE")
    pr(SEP)

    fk_f1 = p1.get("fk_total", 0)
    fk_f3 = p3.get("fk_total", 0)
    fk_delta = fk_f3 - fk_f1

    contacts_f1 = p1.get("contacts") or 0
    contacts_f3 = p3.get("contacts") or 0
    convers_f1 = p1.get("conversations") or 0
    convers_f3 = p3.get("conversations") or 0
    msg_f1 = p1.get("messages") or 0
    msg_f3 = p3.get("messages") or 0

    pr()
    if fk_delta == 0:
        pr("  ✅ FK violations: a migração NÃO introduziu novas violações FK.")
        if fk_f3 > 0:
            pr(f"     As {fk_f3:,} violações restantes são PRÉ-EXISTENTES no DEST restaurado.")
    elif fk_delta > 0:
        pr(f"  ❌ FK violations: a migração introduziu +{fk_delta:,} novas violações FK.")
        pr("     Investigação necessária.")
    else:
        pr(f"  ✅ FK violations: a migração REDUZIU violações FK em {-fk_delta:,}.")

    pr()
    pr("  CRESCIMENTO DO BANCO DEST DE FASE 1 → FASE 3")
    if contacts_f1 and contacts_f3:
        pr(
            f"    contacts:      {contacts_f1:>12,}  →  {contacts_f3:>12,}  ({_delta_pct(contacts_f3, contacts_f1)})"
        )
    if convers_f1 and convers_f3:
        pr(
            f"    conversations: {convers_f1:>12,}  →  {convers_f3:>12,}  ({_delta_pct(convers_f3, convers_f1)})"
        )
    if msg_f1 and msg_f3:
        pr(f"    messages:      {msg_f1:>12,}  →  {msg_f3:>12,}  ({_delta_pct(msg_f3, msg_f1)})")

    pr()
    pr(SEP)

    return buf.getvalue()


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    if len(args) == 3:
        files = [Path(a) for a in args]
    elif len(args) == 0:
        files = autodetect_files()
        if len(files) < 2:
            print(
                "ERRO: não foram encontrados pelo menos 2 arquivos "
                "relatorio_qualidade_dest_*.txt em tmp/",
                file=sys.stderr,
            )
            sys.exit(1)
        # pad: se só 2 arquivos, duplica o 2o como fase2 e 1o como fase1-fallback
        while len(files) < 3:
            files = [files[0]] + files
    else:
        print(
            f"Uso: {sys.argv[0]} [fase1.txt fase2.txt fase3.txt]",
            file=sys.stderr,
        )
        sys.exit(1)

    p1, p2, p3 = [parse_report(f) for f in files]

    _orig = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        texto = gerar_relatorio(p1, p2, p3)
    finally:
        sys.stdout = _orig

    print(texto)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = TMP_DIR / f"relatorio_consolidado_pipeline_{ts}.txt"
    out_path.write_text(texto, encoding="utf-8")
    print(f"Relatório salvo em: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
