# Auditoria geral — PIT PRÊMIOS

**Data:** 03/11/2026  
**Branch auditada:** `audit/backup-restore-safety`  
**Escopo:** `main.py`, `database.py`, `config.py`, `backup_utils.py`, configuração do GitHub Actions, documentação e testes.  
**Banco real:** não foi aberto, copiado, alterado nem migrado durante esta auditoria.

## Validação conjunta

A cadeia de PRs #1 a #6 foi verificada. Todas permanecem abertas, encadeadas e sem merge. O CI da versão acumulada da PR #6 executou os testes em Python 3.11 e 3.12.

Antes desta auditoria complementar, os dois ambientes passaram com 26 testes. Os testes adicionais incluídos nesta auditoria serão executados pelo próximo CI.

## Correções aplicadas nesta auditoria

1. **Bloqueio de contas nos botões:** callbacks agora verificam o bloqueio antes de executar jogos, compras, metas, check-in ou outras ações. Antes, o bloqueio era aplicado aos comandos e mensagens, mas não a todos os botões.
2. **Comprovantes de tarefas após reinício:** a tarefa escolhida para envio de comprovante agora é persistida em SQLite, em vez de ficar somente na memória do processo.
3. **Recuperação de filas grandes:** a inicialização percorre atualizações pendentes em lotes de 500, sem deixar registros acima do primeiro lote esquecidos.
4. **Ordem das mensagens sob sobrecarga:** a fila aplica backpressure em vez de processar uma atualização diretamente no poller quando a capacidade fica cheia. Isso evita contornar a fila serializada por usuário.
5. **Schema:** removidas declarações duplicadas das tabelas de bloqueio, mantendo as tabelas e os dados existentes.

## Achados que ainda exigem correção

### Alta prioridade — idempotência de efeitos financeiros na repetição de atualizações

A fila durável permite recuperar atualizações não concluídas. Porém, algumas operações criam um novo registro financeiro sem uma chave idempotente vinculada ao `update_id`. Se o processo cair depois do commit SQLite e antes de marcar a atualização como concluída, o replay pode repetir a ação.

Áreas especialmente importantes:
- `/resgatar`: pode criar dois pedidos e reservar pontos duas vezes.
- botão `shopbuy:`: pode criar pedidos duplicados e debitar pontos novamente.
- `/addpoints`: pode repetir um ajuste administrativo de saldo.
- Notificações e comunicados podem ser repetidos quando a falha ocorre depois do efeito principal.

As análises de pedidos já usam status pendente e transações, e vários fluxos têm restrições únicas, mas isso não resolve todos os efeitos repetidos causados por replay. A correção recomendada é registrar o `update_id` na mesma transação SQLite que realiza cada efeito, com retorno idempotente para a repetição.

**Situação:** identificado; ainda não corrigido. Não considerar a proteção contra replay financeiro completa até resolver este ponto.

### Proteção de backups e dados pessoais

O arquivo de backup contém saldos, histórico e chaves Pix. O ZIP é validado, mas não é criptografado antes do envio pelo Telegram aos administradores.

**Recomendação:** implementar criptografia autenticada com chave mantida fora do repositório e restringir o acesso/retention dos arquivos. Não armazenar a chave junto do backup.

### Confirmação de pagamentos Pix

A aprovação do saque é manual. O bot informa ao administrador para transferir o Pix antes de clicar em confirmar, mas não verifica a transferência em uma instituição financeira.

**Recomendação:** manter a confirmação restrita a administradores e exigir referência/comprovante da transferência ou integração com provedor de pagamento antes de marcar como pago.

## Limites desta auditoria

- Os testes usam bancos SQLite temporários e isolados.
- O CI não simula chamadas reais à API do Telegram, envio de Pix nem o ambiente de hospedagem Discloud.
- Não foi feita restauração sobre o banco de produção.
- Não foi feito merge das PRs nem deploy.

## Próxima correção obrigatória

Implementar idempotência por `update_id` dentro das transações de todas as operações que alteram saldo, pedidos, estoque ou pagamentos, com testes de replay após commit e antes da confirmação do processamento.


## Complemento — idempotência por atualização do Telegram

**Implementado nesta revisão:** a tabela não destrutiva `idempotency_keys` registra o `update_id`, o tipo da operação e seu resultado na mesma transação que altera saldo/pedido/estoque. O replay da mesma atualização devolve o identificador original ou ignora o ajuste já aplicado, sem repetir o efeito financeiro.

Operações cobertas:
- criação de resgate (`/resgatar`);
- compra na loja (`shopbuy:`), incluindo reserva de estoque;
- criação de saque (`/sacar`);
- ajuste administrativo de pontos (`/addpoints`).

A chave não pode ser reutilizada por outro tipo de operação. Os registros idempotentes são retidos por 30 dias e removidos somente pela rotina de limpeza.

**Testes adicionais:** 5 testes verificam replay de cada operação e rejeição de reutilização da chave por ação diferente. A suíte acumulada alcança 34 testes; o CI está sendo executado novamente em Python 3.11 e 3.12 para o commit mais recente.

**Limite remanescente:** a proteção cobre os quatro fluxos de escrita financeira listados. Outros fluxos que já possuem trava de estado/constraint própria (check-in diário, jogos diários, metas únicas, aprovação de análises e submissões de tarefa) continuam dependendo dessas regras específicas. Efeitos externos, como envio de mensagens do Telegram, podem ser repetidos se o processo cair após o commit; a garantia aqui é não duplicar a alteração financeira local.
