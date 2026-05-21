# Final Status — 2026-05-21

**Branch**: master
**Sessão**: 2026-05-21 (início) → 2026-05-21 (encerramento)

## IMPs/Entregas Concluídas Nesta Sessão
- ✅ S22-01: análise técnica de causa (migração vs visibilidade) para Guaxupé.
- ✅ S22-02: diagnóstico conclusivo do estado do banco DEV (`chatwoot004_dev1_db`).
- ✅ S22-03: coleta de evidência do container parado no wfdb01 (logs + env + exit code).
- ✅ S22-04: criação de coletor reutilizável chat x synchat com saída JSON.
- ✅ S22-05: execução de coletas e consolidação de snapshots.
- ✅ S22-06: relatório formal da investigação chat x synchat.
- ✅ S22-07: plano e lista de tarefas para reset/revisão profunda em modo DEV-only.
- ✅ S22-END: ajuste da política de reconciliação (`ID > nome`) com auditoria explícita.

## Estado Geral
| Item | Status | Observação |
|------|--------|------------|
| Investigação funcional chat x synchat | ✅ Concluído | Evidência de front consolidada |
| Plano DEV-only (reset + revisão) | ✅ Concluído | Aguardando confirmação de escopo |
| Execução destrutiva (limpeza real) | ⏸ Bloqueado | Depende de confirmações operacionais |
| Homologação final em DEV | 🔄 Pendente | Após Fase A/B/C/D |

## Decisões Técnicas da Sessão
- D-S22-01: adotar `ID > nome` em conflitos de reconciliação.
- D-S22-02: exigir log estruturado de divergências (`source_id`, `dest_id`, nomes, decisão aplicada).
- D-S22-03: manter gate DEV-only como pré-condição para qualquer passo executável.

## Próximas Ações (P0 para próxima sessão)
1. Confirmar escopo exato da limpeza seletiva e base-alvo operacional (DEV-only).
2. Implementar guardrails da Fase A (hard gates de ambiente/chaves).
3. Implementar dry-run da Fase B com relatório JSON por tabela/account.
4. Revisar output do dry-run e aprovar escopo final antes de remoção real.

## Contexto para Recuperação Rápida
- Artefato de investigação: `docs/SESSIONS/2026-05-21/INVESTIGACAO_GUAXUPE_CHAT_SYNCHAT_2026-05-21.md`.
- Artefato de plano/tarefas: `docs/SESSIONS/2026-05-21/PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md`.
- O próximo passo recomendado permanece: iniciar Fase A/B apenas após confirmação das dúvidas de escopo.
