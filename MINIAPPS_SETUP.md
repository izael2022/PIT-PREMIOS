# Mini Apps PIT PRÊMIOS — configuração

## O que existe nesta branch
- Interfaces estáticas em `miniapps/` para calendário, baús surpresa e roleta.
- Workflow `.github/workflows/pages.yml` para publicar a pasta `miniapps` no GitHub Pages após merge na `main`.
- API HTTP interna no processo Python, com validação HMAC de `Telegram.WebApp.initData`, limite de corpo, CORS restrito e rotas de saldo/check-in/baú/roleta.
- Modo de manutenção persistente no `bot_settings`, administrável pelo painel.

## Ainda não publicar para usuários
O Pages não fornece a API. A API precisa de um endereço HTTPS público, encaminhado para a porta interna configurada por `PORT` (padrão 8080). O arquivo `miniapps/assets/config.js` deve receber a URL HTTPS pública em `window.PIT_API_BASE`. O domínio da API deve ser adicionado a `MINIAPP_ALLOWED_ORIGINS`? Não: essa variável aceita as origens do front-end, atualmente `https://izael2022.github.io`.

Antes de produção, confirmar que a modalidade de hospedagem do bot expõe uma porta HTTP pública e que o proxy fornece HTTPS. A configuração atual `discloud.config` é `TYPE=bot`; não presumir que a porta 8080 esteja acessível externamente. Não alterar o tipo da aplicação nem fazer deploy sem validação e autorização.

## Segurança
- A API exige Authorization `tma <initData>`, valida HMAC usando BOT_TOKEN no servidor e rejeita dados expirados (mais de 24 horas).
- Nunca inserir BOT_TOKEN, ADMIN_IDS ou chaves no JavaScript público.
- Calendário usa o mecanismo atual de check-in diário e sequência DAILY_REWARDS.
- Baú e roleta usam `play_daily_game`, que registra a tentativa e os pontos em transação SQLite e impede segunda tentativa no mesmo dia por jogo.
- Os valores de prêmio são escolhidos no servidor; não confiar em valores enviados pelo navegador.
- As recompensas atuais são simples valores de pontos. Ainda não existe painel para configurar campanhas, períodos, probabilidades ou conteúdo dos eventos.

## Limitações de produto
O calendário desenha o mês, mas o backend atual só tem o estado de check-in atual/sequência, não um histórico mensal completo por data. Para mostrar corretamente todos os dias já coletados será necessária uma tabela histórica aditiva. O evento surpresa ainda funciona como baú diário, não como campanha agendada. A roleta especial reaproveita a tentativa diária da roleta existente.
