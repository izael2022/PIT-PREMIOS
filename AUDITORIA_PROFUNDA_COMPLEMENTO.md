# Complemento da auditoria profunda — PIT PRÊMIOS

## Alterações desta rodada

- O painel de saúde separa trabalhadores criados pelo executor, atualizações em processamento, atualizações aguardando por usuário e usuários com fila ativa.
- O processo contabiliza atualizações concluídas e falhas desde a inicialização atual. Esses contadores reiniciam quando o processo reinicia e não são apresentados como histórico permanente.
- O log periódico de saúde utiliza os mesmos indicadores do painel administrativo, evitando interpretar threads criadas como trabalhadores necessariamente ocupados.
- O painel financeiro compara o total de pontos nas carteiras com o saldo líquido do extrato (point_history). Uma diferença é sinalizada para investigação; o sistema não corrige saldos automaticamente.
- O painel financeiro passa a mostrar pontos reservados em resgates e pedidos da loja pendentes.
- Removidas declarações duplicadas de tabelas de bloqueio no script de inicialização. As tabelas existentes são mantidas; nenhuma tabela ou registro é apagado.
- Adicionados testes de conciliação financeira, preservação de saldo após nova inicialização do schema e unicidade da tabela de bloqueios.

## Limites e cuidados

- A conciliação é um indicador de auditoria, não uma autorização para alterar saldos. Dados históricos anteriores ao extrato podem produzir diferenças legítimas; investigar antes de qualquer ajuste.
- Os contadores de processamento são relativos à vida do processo e não substituem métricas históricas externas.
- O CI usa bancos temporários. Nenhum banco da Discloud foi aberto, migrado ou alterado.
- Não foi feita integração bancária para validar transferências Pix. A confirmação de pagamento continua dependendo do procedimento administrativo e da conferência externa.
- A auditoria administrativa já registra comandos e callbacks administrativos; esta rodada acrescenta testes de regressão para a conciliação e para a inicialização não destrutiva.

## Implantação

Atualizar somente o código da aplicação. Manter DATABASE_PATH, BOT_TOKEN, ADMIN_IDS, BACKUP_ENCRYPTION_KEY e MONITOR_HEARTBEAT_URL nas variáveis secretas/configuração da hospedagem. Não incluir nem substituir data/pit_premios.db.
