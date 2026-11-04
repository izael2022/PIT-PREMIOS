# PIT PRÊMIOS

Bot de recompensas para Telegram em Python 3.11+ e SQLite, usando apenas a biblioteca padrão do Python.

## Funcionalidades
- Cadastro e link de indicação.
- Pontos por novo indicado.
- Saldo, ranking e bônus diário.
- Histórico de créditos e débitos.
- Solicitação de resgate com reserva de pontos.
- Aprovação/rejeição de resgates; rejeição devolve pontos.
- Administração: estatísticas, ajuste de pontos e ativação manual de VIP.
- Banco SQLite com transações, índices e WAL.

## Configuração
Configure as variáveis diretamente no painel da hospedagem:
- BOT_TOKEN: token secreto do Telegram.
- ADMIN_IDS: IDs numéricos separados por vírgula.
- DATABASE_PATH: padrão data/pit_premios.db.
- POINTS_PER_REFERRAL: pontos por indicação válida; padrão 100.
- DAILY_REWARDS: sequência de pontos do check-in, separados por vírgula; padrão `3,4,5,6,7,8,10`. Após o último dia, a sequência recomeça.
- MIN_REDEEM_POINTS: mínimo para resgate/saque; padrão 1000.

## Execução
Python 3.11 ou superior:
```bash
python main.py
```

O projeto não precisa instalar bibliotecas externas. O processo consulta a API oficial do Telegram por long polling.

## Comandos
Participantes: /start, /saldo, /ranking, /diario, /resgatar PONTOS DESCRIÇÃO

Administrador: /admin, /stats, /addpoints ID QUANTIDADE, /setvip ID on|off, /pedidos.

## Dados e segurança
O banco continua em data/pit_premios.db e usa as mesmas tabelas da versão anterior. Não apague nem substitua esse arquivo durante a atualização. Faça backup antes de qualquer migração de hospedagem.

Nunca coloque BOT_TOKEN no GitHub. Cadastre o token nas variáveis de ambiente da hospedagem.

## Limitações
- Resgates são analisados manualmente; o bot não realiza pagamentos PIX.
- VIP é ativado manualmente.
- Ainda é necessário testar os comandos na hospedagem após o deploy.


Auditoria profunda em andamento.
