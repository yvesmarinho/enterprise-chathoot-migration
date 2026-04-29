# docs/debates/ — Debates Técnicos e de Produto

Armazena debates estruturados sobre decisões importantes do projeto.

## 🎯 Objetivo

Documentar o **processo de decisão** — não apenas o resultado, mas também:
- Alternativas consideradas
- Prós e contras de cada opção
- Contexto da decisão
- Participantes do debate

## 📝 Formato

Use o template de debate (agent `@template-architect` ou manual):

```markdown
# DEBATE: [Título da Questão]

**Data**: YYYY-MM-DD
**Participantes**: @user1, @user2, AI Agent
**Contexto**: [Por que este debate é necessário?]

## Questão Central
[Pergunta clara que precisa ser respondida]

## Alternativas

### Opção A: [Nome]
**Prós**: ...
**Contras**: ...

### Opção B: [Nome]
**Prós**: ...
**Contras**: ...

## Decisão
[Escolha + Justificativa]

## Ações
- [ ] Implementar X
- [ ] Documentar em decisions/
```

## 🔍 Quando usar

- Mudanças de arquitetura significativas
- Escolha entre tecnologias/frameworks
- Decisões que afetam múltiplos times
- Trade-offs complexos

## 📂 Nomenclatura

`DEBATE_[TOPICO]_YYYY-MM-DD.md`

Exemplos:
- `DEBATE_SPEC_DRIVEN_DEVELOPMENT_2026-04-05.md`
- `DEBATE_ESCOLHA_ORM_2026-03-15.md`

## 🔗 Ver também

- [decisions/](../decisions/) — Registro formal de decisões (ADRs)
- [retrospectives/](../retrospectives/) — Aprendizados pós-sprint

## 📋 Debates deste projeto

| ID | Arquivo | Assunto | Status |
|----|---------|---------|--------|
| D3 | [D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md](D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md) | Estratégia MERGE vs incremental | Resolvido |
| D4 | [D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md](D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md) | Contatos órfãos | Resolvido |
| D5 | [D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md](D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md) | Spec validação via API | Resolvido |
| D6 | [D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md](D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md) | Validação hash/integridade | Resolvido |
| D7 | [D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md](D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md) | Visibilidade conversas Marcos | Resolvido |
| D8 | [D8-ANALISE-404-CHATWOOT-API-2026-04-23.md](D8-ANALISE-404-CHATWOOT-API-2026-04-23.md) | HTTP 404 API + 14 inboxes invisíveis | Resolvido (código corrigido) |
| Q1 | [Q1-QUESTIONARIO-INFORMACOES-FALTANTES-2026-04-23.md](Q1-QUESTIONARIO-INFORMACOES-FALTANTES-2026-04-23.md) | Questionário decisões pendentes | **Pendente resposta** |
