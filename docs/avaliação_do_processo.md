# Avaliação do processo de migração

## Pontos passíveis de melhoria identificados durante a execução da migração em produção:

- informações das conexões fixas no código.
- o processo é de merge, mas não havia um processo para migrar os usuários que não estavam no destino.
- existia o código para ser executado em container no servidor próximo ao banco de dados, mas o RUNBOOK não utilizou esse recruso.
