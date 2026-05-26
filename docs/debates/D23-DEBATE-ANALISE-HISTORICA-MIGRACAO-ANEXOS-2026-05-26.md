# D23 — DEBATE: Análise Histórica da Migração de Mensagens e Anexos no DEV

**Data**: 2026-05-26
**Sessão**: 26 (S26)
**Ambiente**: DEV — `vya-chat-dev.vya.digital` → banco `chatwoot004_dev1_db`
**Account afetada**: Unimed Guaxupé — `account_id=68` (SOURCE: `id=25`)
**Escopo**: Histórico da migração, mensagens, anexos e cadeia ActiveStorage

---

## Sumário Executivo

A análise histórica mostra um padrão consistente de **migração parcial**:

- as conversas e mensagens passaram a existir e a ser exibidas no DEV;
- os anexos, porém, permaneceram em uma cadeia incompleta ou inconsistente;
- a aplicação então passou a falhar ao tentar serializar conversas com anexos, porque a cadeia esperada de `attachments` + `active_storage_attachments` + `active_storage_blobs` não estava íntegra para todos os casos;
- em paralelo, a migração encontrou um segundo problema de processo: `active_storage_blobs.key` já existia no DEST em outros registros, exigindo deduplicação por chave para permitir reexecução idempotente.

Em resumo: **o histórico não aponta para uma falha isolada de UI, mas para uma sequência de migrações parcialmente bem-sucedidas, onde o núcleo de mensagens foi preservado e a camada de anexos/ActiveStorage ficou incompleta**.

---

## Questão Central

O que, historicamente, explica o cenário em que **as mensagens aparecem no DEV, mas os anexos não**?

---

## Linha do Tempo Histórica

### 1. D15 — Descoberta inicial de anexos quebrados

Arquivo: [D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md)

O primeiro marco histórico foi a validação S3 pós-migração.
A descoberta foi objetiva:

- os metadados dos attachments estavam no banco;
- os arquivos físicos retornavam HTTP 404 em larga escala;
- a taxa de sucesso observada na amostra foi de 26%, com 74% de falha;
- a documentação já apontava que a migração tinha coberto **somente os dados relacionais**, não garantindo a acessibilidade real dos arquivos.

Ponto importante do histórico:
- nessa etapa, o problema ainda era interpretado como um problema de **persistência/availability dos anexos**, não como um problema de renderização.

### 2. D16 — Conversas com anexo passaram a quebrar a serialização

Arquivo: [D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md](D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md)

No passo seguinte, o problema evoluiu de “anexo inacessível” para “conversa com anexo gera 500 ao abrir” no DEV.
O histórico D16 registrou:

- requisição autenticada ao endpoint de conversas com `inbox_id=526` e `status=all`;
- stack trace apontando para `Attachment#file_metadata`;
- `ActionView::Template::Error` ao serializar a conversa;
- ausência de vínculos em `active_storage_attachments` e `active_storage_blobs` para os anexos migrados.

O dado histórico mais importante é este:

- **mensagens sem anexo continuavam abrindo**;
- **mensagens com anexo causavam 500**.

Isso estabelece que o fenômeno já era claramente **seletivo por presença de anexo**, e não uma falha geral de account, inbox ou autenticação.

### 3. D18 — Última migração com sucesso parcial, mas sem ActiveStorage

Arquivo: [D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md](D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md)

D18 consolidou o diagnóstico histórico com mais precisão.
A última migração foi registrada como bem-sucedida no que diz respeito ao volume principal:

- conversas migradas;
- mensagens migradas;
- contacts migrados;
- FK integrity limpa.

Mas a parte de attachments/ActiveStorage ficou assim:

- `attachments` migrados: presentes;
- `active_storage_attachments`: 0;
- `active_storage_blobs`: 0;
- cobertura efetiva: 0%.

O ponto histórico mais sensível de D18 é que a análise mostrou que **o SOURCE também não possuía ActiveStorage** na estrutura esperada pelo DEV atual.
Isso reforça que o pipeline tinha um gap estrutural: o core de mensagens vinha sendo migrado, mas a cadeia que a UI atual do Chatwoot precisa para renderizar anexos não estava sendo reconstruída.

### 4. D19 — Tentativa de corrigir o gap encontrou blobs já existentes no DEST

Arquivo: [D19-ERRO-CHAVE-DUPLICADA-ACTIVE-STORAGE-BLOBS-2026-05-26.md](D19-ERRO-CHAVE-DUPLICADA-ACTIVE-STORAGE-BLOBS-2026-05-26.md)

Quando o pipeline tentou incorporar ActiveStorage, surgiu um segundo obstáculo histórico:

- `active_storage_blobs` falhou por `UniqueViolation` em `index_active_storage_blobs_on_key`;
- o mesmo `key` já existia no DEST;
- o migrator precisou passar a deduplicar por `key` para não quebrar em reexecuções sobre bancos parcialmente preenchidos.

Esse marco é importante porque mostra que o problema não era apenas “faltou migrar anexos”, mas também:

- o DEST já tinha blobs pré-existentes de outras contas;
- o pipeline precisava ser idempotente;
- qualquer correção de anexos precisava respeitar a realidade de um banco parcialmente populado.

---

## Evidências Recentes que Fecham a Análise Histórica

### 1. O canal da inbox 526 está íntegro

A investigação recente confirmou que a inbox 526 não está “quebrada” por canal dangling:

- `channel_type = Channel::Whatsapp`;
- `channel_id = 37`;
- registro existe em `channel_whatsapp`.

Portanto, o problema não é invisibilidade da inbox por FK de canal.

### 2. Há conversas que funcionam e conversas que quebram

Os logs recentes mostraram um padrão seletivo:

- a conversa `3756` retornou `200`;
- a conversa `3999` retornou `500`;
- ambas pertencem ao mesmo account e inbox, mas a `3999` contém anexos PDF e aciona o erro durante a serialização.

Isso confirma que o problema é **data-dependent** dentro do histórico migrado.

### 3. A falha acontece no momento em que a conversa é serializada

O log atual mostrou:

- o `Conversation Load` ocorre corretamente;
- o `Attachment Load` ocorre corretamente;
- o `ActiveStorage::Attachment` e o `ActiveStorage::Blob` também são encontrados;
- a exceção explode durante `Attachment#file_metadata`.

Mesmo assim, o contexto histórico segue o mesmo: a cadeia de anexos não estava confiável o suficiente para o runtime do Chatwoot no DEV.

---

## Análise da Cadeia de Migração

### O que foi migrado com sucesso

- accounts;
- conversations;
- messages;
- contacts;
- FKs principais;
- parte do volume de attachments como registros de banco.

### O que permaneceu incompleto

- a reconstrução consistente da camada ActiveStorage;
- a garantia de que todos os attachments pudessem ser resolvidos pelo runtime da UI;
- a deduplicação segura de blobs já existentes no DEST.

### Resultado operacional

O sistema ficou em um estado intermediário:

- mensagens aparecem;
- conversas existem;
- alguns anexos podem ser renderizados;
- outros acionam caminho de erro por inconsistência histórica na cadeia de migração.

---

## Alternativas Consideradas Historicamente

### Alternativa A: Culpar a aplicação

**Prós**:
- o stack trace explode em código Ruby da app;
- a UI mostra erro na abertura da conversa.

**Contras**:
- o erro só aparece em um subconjunto de dados;
- a história da migração já havia documentado gaps de attachments;
- o problema correlaciona com a integridade da cadeia de dados, não com o fluxo funcional geral.

### Alternativa B: Considerar o problema como incompleto no processo de migração

**Prós**:
- explica a sequência D15 → D16 → D18;
- explica por que mensagens aparecem e anexos não;
- explica por que a correção exigiu ajuste de idempotência no `active_storage_blobs`;
- compatível com o fato de o banco já estar parcialmente populado.

**Contras**:
- exige aceitar que a app é apenas a superfície onde o gap de dados se manifesta.

**Decisão histórica**: esta é a explicação mais consistente com o conjunto de evidências.

---

## Conclusão Histórica

A documentação histórica converge para a mesma leitura:

1. o core da migração funcionou e trouxe mensagens/conversas para o DEV;
2. os anexos ficaram em um estado incompleto por ausência de ActiveStorage ou por inconsistência na cadeia de resolução;
3. ao tentar corrigir isso, o pipeline encontrou blobs já existentes e precisou ser tornado idempotente;
4. o comportamento final é de **migração parcial com sucesso funcional nas mensagens e falha na camada de anexos**.

Portanto, quando o usuário vê **mensagens exibidas, mas anexos ausentes ou mensagens que falham ao abrir**, isso é compatível com a cronologia histórica da migração: o problema nasce no processo de migração dos anexos e só aparece na aplicação na hora da renderização.

---

## Decisão

A interpretação correta é tratar o caso como **análise histórica de processo de migração**:

- o fluxo de mensagens/conversas foi parcialmente bem-sucedido;
- a camada de anexos/ActiveStorage não foi consolidada de forma completa;
- o destino final é um estado híbrido, em que parte do conteúdo funciona e parte depende de dados não migrados ou não deduplicados corretamente.

---

## Ações Derivadas

- [ ] Manter a documentação do histórico como referência principal para incidentes de anexos.
- [ ] Tratar ActiveStorage como etapa explícita do workflow de migração, com validação própria.
- [ ] Garantir deduplicação por `key` para `active_storage_blobs` em bancos parcialmente preenchidos.
- [ ] Validar, por account, a cobertura de `attachments` + `active_storage_attachments` + `active_storage_blobs` antes de aceitar a migração como concluída.
- [ ] Registrar no runbook que “mensagens visíveis” não equivale a “anexos migrados e renderizáveis”.

---

## Evidências e Referências

- [D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md)
- [D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md](D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md)
- [D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md](D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md)
- [D19-ERRO-CHAVE-DUPLICADA-ACTIVE-STORAGE-BLOBS-2026-05-26.md](D19-ERRO-CHAVE-DUPLICADA-ACTIVE-STORAGE-BLOBS-2026-05-26.md)
- [DAILY_ACTIVITIES_2026-05-26.md](../SESSIONS/2026-05-26/DAILY_ACTIVITIES_2026-05-26.md)
- [messages_error.log](../../logs/messages_error.log)
