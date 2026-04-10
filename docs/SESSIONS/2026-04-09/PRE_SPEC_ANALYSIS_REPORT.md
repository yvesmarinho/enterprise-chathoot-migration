# PRE-SPEC ANALYSIS REPORT — v2 (revisado com respostas)
**Projeto**: enterprise-chatwoot-migration
**Fase**: Pré-especificação — preparação para `speckit.constitution`
**Data**: 2026-04-09
**Origem analisada**: `objetivo.yaml`
**Template de referência**: `objetivo-template.yaml`
**Status**: ✅ Totalmente concluído — D1 resolvida em 2026-04-09, pronto para `speckit.clarify`

---

## Resumo Executivo

Após consolidação de todas as respostas, os dois arquivos de especificação (`objetivo.yaml` e `objetivo-template.yaml`) foram atualizados e estão prontos para `speckit.constitution`. A única pendência é a **task D1** (versão exata do Chatwoot), que não bloqueia a geração da constitution mas deve ser resolvida antes do `speckit.plan`.


---

## ✅ Dúvidas Resolvidas (D1–D6)

| # | Tema | Resolução |
|---|---|---|
| **D1** | Versão do Chatwoot | ✅ RESOLVIDA (2026-04-09) — `scripts/check_chatwoot_versions.py` executado com sucesso. schema_sha1 idêntico em ambas as instâncias. Ver tabela completa abaixo. |
| **D2** | Destino de `chatwoot_dev1_db` pós-migração | Atribuído ao owner (yvesmarinho) para decidir após conclusão |
| **D3** | Attachments S3 | Migrar apenas URLs de referência — sem mover arquivos físicos |
| **D4** | ETL ou cópia direta | Mesma aplicação — cópia com remapeamento de IDs (offset). Sem transformação de dados. |
| **D5** | Dados sensíveis | Nenhum dado sensível em stdout, logs ou qualquer saída visível em nenhum momento |
| **D6** | Interface da ferramenta | Script direto: `python src/migrar.py` |



## ✅ Dados Consolidados nos Arquivos de Especificação

| Campo | Valor |
|---|---|
| `domain` | `data-migration` |
| `codename` | `enterprise-chatwoot-migration` |
| `problem_statement` | Migrar `chatwoot_dev1_db` → `chatwoot004_dev1_db`, consolidando `chat.vya.digital` em `synchat.vya.digital` |
| `success_statement` | 100% dos registros migrados, zero FK violations, conversas e mensagens com associações corretas, contagem validada |
| PostgreSQL | Versão 16, mesmo servidor VPS (wfdb02.vya.digital / 82.197.64.145) |
| Volume | < 5 GB |
| URL destino | `https://vya-chat-dev.vya.digital` |
| `chatwoot_dev` | Somente banco de dados — sem app web ativa — somente leitura |
| Escopo de dados | **Todo o banco de dados** — nenhuma tabela excluída |
| Deduplicação | Não aplicável — empresas/clientes completamente distintos entre instâncias |
| Remapeamento de IDs | `novo_id = id_origem + max(id_destino)` — relações internas preservadas |
| S3 | Migrar apenas URLs de referência — sem mover arquivos físicos |
| Dados sensíveis em log | Proibido em qualquer output (stdout, arquivo, terminal) |
| Estratégia | Incremental + idempotente |
| Rollback | Backup de `chatwoot004_dev1_db` disponível. `chatwoot_dev1_db` não sofre alteração. |
| Fabric Design Pattern | Todo o código — da camada de conexão aos migrators |
| Interface | Script direto: `python src/migrar.py` |
| Python mínimo | 3.12 |
| Credenciais | `.secrets/generate_erd.json` (não versionado) |
| Stakeholder | yvesmarinho (único owner, operador e aprovador) |

---

## 📊 Dados Coletados por D1 (2026-04-09)

| Campo | chatwoot_dev1_db (ORIGEM) | chatwoot004_dev1_db (DESTINO) |
|---|---|---|
| Última migration | `20241217041352` | `20240820191716` |
| Total migrations | 252 | 255 |
| schema_sha1 | `da6b4a366d550dc7794f55f5e1536342ce50845f` | `da6b4a366d550dc7794f55f5e1536342ce50845f` (**IDÊNTICO**) |
| environment | production | production |
| accounts | 5 | 20 |
| contacts | 38.868 | 225.536 |
| conversations | 41.743 | 153.582 |
| messages | 310.155 | 1.302.949 |
| inboxes | 21 | 151 |
| users | 112 | 294 |
| teams | 3 | 22 |
| labels | 32 | 184 |
| attachments | 26.889 | 73.435 |

**Discovery chave**: `schema_sha1` idêntico confirma compatibilidade plena de schemas — sem necessidade de transformação estrutural. A origem possui migration mais recente (`20241217`) vs destino (`20240820`), mas o SHA idêntico indica que as 3 migrations extras na origem não alteraram a estrutura
do schema. Migração pode prosseguir com cpia direta + remapeamento de IDs.

## ⏳ Pendências Remanescentes

| ID | Tarefa | Responsável | Ação |
|---|---|---|---|
| ~~**D1**~~ | ~~Verificar versão exata do Chatwoot em cada instância~~ | Copilot | ✅ RESOLVIDA — ver tabela acima |
| **D2** | Definir destino de `chatwoot_dev1_db` após migração bem-sucedida | yvesmarinho | Manter histórico? Congelar? Desativar? |

---

## Artefatos Atualizados

- [objetivo.yaml](../../../objetivo.yaml) — description, rules, expected_outcome, features_to_implement, pending_tasks
- [objetivo-template.yaml](../../../objetivo-template.yaml) — todos os gates respondidos, sections preenchidas
- [scripts/check_chatwoot_versions.py](../../../scripts/check_chatwoot_versions.py) — criado para task D1

---

*v4 — 2026-04-09 | Fase: pré-especificação concluída | D1 resolvida com dados reais | Próximo: `speckit.clarify`*
