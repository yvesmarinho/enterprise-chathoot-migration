#!/usr/bin/env python3
"""
migrate_all_accounts.py — Migra TODOS os accounts SOURCE → DEST em sequência.

Consulta todos os accounts do SOURCE, executa 01_migrar_account.py para cada
um em subprocesso isolado, e grava um relatório final em JSON.

Uso:
    python app/migrate_all_accounts.py
    python app/migrate_all_accounts.py --dry-run

Saída:
    .tmp/migrate_all_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from app.db import cur, src  # noqa: E402

_DRY_RUN = "--dry-run" in sys.argv
_OUT_DIR = _ROOT / ".tmp"


def _fmt_elapsed(seconds: float) -> str:
    """Formata segundos em Xh Ym Zs, Ym Zs ou Zs."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
_OUT = _ROOT / ".tmp" / f"migrate_all_{_TS}.json"


def get_source_accounts() -> list[dict]:
    """Retorna todos os accounts do SOURCE ordenados por id."""
    sc = src()
    with cur(sc) as c:
        c.execute("SELECT id, name, status FROM public.accounts ORDER BY id")
        rows = c.fetchall()
    sc.close()
    return [dict(r) for r in rows]


def run_account(name: str) -> dict:
    """Executa 01_migrar_account.py para o account informado.

    Retorna dict com: name, exit_code, elapsed_s, status.
    Output é transmitido em tempo real para o terminal.
    """
    cmd = [sys.executable, str(_ROOT / "app" / "01_migrar_account.py"), name]
    if _DRY_RUN:
        cmd.append("--dry-run")

    print(f"\n{'#'*65}")
    print(f"  INICIANDO: '{name}'  {'[DRY-RUN]' if _DRY_RUN else ''}")
    print(f"{'#'*65}\n")

    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = round(time.monotonic() - t0, 1)

    status = "OK" if result.returncode == 0 else f"ERRO (exit={result.returncode})"
    print(f"\n→ '{name}' concluído em {_fmt_elapsed(elapsed)} — {status}")

    return {
        "name": name,
        "exit_code": result.returncode,
        "elapsed_s": elapsed,
        "elapsed_fmt": _fmt_elapsed(elapsed),
        "status": status,
    }


def main() -> None:
    t_start_dt = datetime.now()
    print("=" * 65)
    print(f"  MIGRAÇÃO COMPLETA — TODOS OS ACCOUNTS")
    print(f"  Modo     : {'DRY-RUN' if _DRY_RUN else 'REAL'}")
    print(f"  Início   : {t_start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    accounts = get_source_accounts()
    print(f"\nAccounts encontrados no SOURCE ({len(accounts)}):")
    for acc in accounts:
        print(f"  id={acc['id']}  '{acc['name']}'  status={acc['status']}")

    report = {
        "timestamp_start": t_start_dt.strftime("%Y%m%d_%H%M%S"),
        "dry_run": _DRY_RUN,
        "accounts_source": accounts,
        "results": [],
    }

    total_t0 = time.monotonic()
    for acc in accounts:
        result = run_account(acc["name"])
        result["src_id"] = acc["id"]
        report["results"].append(result)

    total_elapsed = round(time.monotonic() - total_t0, 1)
    t_end_dt = datetime.now()
    report["total_elapsed_s"] = total_elapsed
    report["total_elapsed_fmt"] = _fmt_elapsed(total_elapsed)
    report["timestamp_end"] = t_end_dt.strftime("%Y%m%d_%H%M%S")

    # Resumo final
    ok = [r for r in report["results"] if r["exit_code"] == 0]
    fail = [r for r in report["results"] if r["exit_code"] != 0]

    print(f"\n{'='*65}")
    print(f"  MIGRAÇÃO COMPLETA CONCLUÍDA")
    print(f"  Início     : {t_start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Fim        : {t_end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Decorrido  : {_fmt_elapsed(total_elapsed)}")
    print(f"  Accounts   : {len(accounts)} total | {len(ok)} OK | {len(fail)} ERRO")
    print(f"  Detalhes por account:")
    for r in report["results"]:
        icon = "✅" if r["exit_code"] == 0 else "❌"
        print(f"    {icon} [{r['elapsed_fmt']:>10}]  {r['name']}  — {r['status']}")
    if fail:
        print(f"\n  FALHAS:")
        for r in fail:
            print(f"    '{r['name']}' exit={r['exit_code']}")
    print(f"{'='*65}\n")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = _OUT_DIR / f"migrate_all_{t_start_dt.strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    print(f"Relatório salvo em: {out_file}")

    sys.exit(0 if not fail else 1)


if __name__ == "__main__":
    main()
