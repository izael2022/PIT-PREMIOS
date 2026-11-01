# PIT PRÊMIOS

Bot de recompensas Telegram em Python 3.11+, aiogram 3 e SQLite.

## Funcionalidades desta versão inicial
- Cadastro por ID do Telegram e link de indicação.
- Crédito de pontos por novo indicado (configurável).
- Saldo, ranking e bônus diário.
- Histórico contábil de créditos e débitos.
- Solicitação de resgate com reserva de pontos.
- Aprovação/rejeição de resgates; rejeição devolve pontos.
- Painel administrativo: estatísticas, ajuste de pontos e ativação manual de VIP.
- SQLite com foreign keys, WAL e transações para operações de saldo.

## Instalação
1. Crie o bot com @BotFather e copie o token.
2. Copie .env.example para .env.
3. Configure BOT_TOKEN e ADMIN_IDS (ID numérico do administrador).
4. Instale: pip install -r requirements.txt
5. Inicie: python main.py

Nunca envie .env para o GitHub. O banco em data/ também é local e ignorado pelo Git.

## Comandos de participante
/start, /saldo, /ranking, /diario, /resgatar PONTOS DESCRIÇÃO

## Comandos administrativos
/admin, /stats, /addpoints ID QUANTIDADE, /setvip ID on|off, /pedidos.
Os botões em /pedidos permitem aprovar ou rejeitar cada solicitação.

## Configurações
BOT_TOKEN: token secreto do Telegram.
ADMIN_IDS: IDs numéricos separados por vírgula.
DATABASE_PATH: caminho do SQLite (padrão data/pit_premios.db).
POINTS_PER_REFERRAL: pontos por indicação (padrão 10).
DAILY_REWARD: bônus diário (padrão 2).
MIN_REDEEM_POINTS: mínimo para resgatar (padrão 100).

## Limitações que precisam ser resolvidas antes de produção
- Não há pagamento PIX automático: aprovação é apenas controle administrativo e o pagamento deve ser feito e confirmado manualmente.
- VIP é ativado manualmente; não há cobrança, validade ou códigos VIP.
- Não há antifraude avançado para indicações. Não anuncie recompensas em dinheiro antes de definir limites e validações.
- O texto de prêmio no resgate é livre e não comprova pagamento.
- O bônus diário usa a data local do servidor. Configure o fuso horário do host para America/Recife ou altere a implementação para timezone explícito.
- Ainda não foram executados testes integrados com Telegram/Discloud. Faça teste com bot privado e banco de homologação antes de produção.
- Recomendado implementar logs de auditoria administrativos, limites de taxa, bloqueio/denúncia de abuso, política de privacidade e backup automático do SQLite.

## Discloud
Configure as variáveis de ambiente no painel, instale requirements.txt e use python main.py como comando. Não coloque token no código nem no repositório.
