# Mini Apps PIT PRÊMIOS — configuração

## O que existe nesta branch
- Interfaces estáticas em `miniapps/` para calendário, baús surpresa e roleta.
- Workflow `.github/workflows/pages.yml` para publicar a pasta `miniapps` no GitHub Pages após merge na `main`.
- API HTTP interna no processo Python, com validação HMAC de `Telegram.WebApp.initData`, limite de corpo, CORS restrito e rotas de saldo/check-in/baú/roleta.
- Modo de manutenção persistente no `bot_settings`, administrável pelo painel.

## Ainda não publicar para usuários
O Pages não fornece a API. A API precisa de um endereço HTTPS público, encaminhado para a porta interna configurada por `PORT` (padrão 8080). O arquivo `miniapps/assets/config.js` deve receber a URL HTTPS pública em `window.PIT_API_BASE`. O domínio da API deve ser adicionado a `MINIAPP_ALLOWED_ORIGINS`? Não: essa variável aceita as origens do front-end, atualmente `https://izael2022.github.io`.

Arquitetura escolhida: manter o bot Telegram e a API no MESMO processo/aplicação Discloud. Isso garante que ambos usem o mesmo arquivo SQLite e evita sincronização ou cópia de saldos. A configuração preparada nesta branch muda o app existente para `TYPE=site`, `ID=pitpremios-central`, `MAIN=main.py` e `RAM=512`. O processo Python continua executando o polling do Telegram e também escuta HTTP em `0.0.0.0:8080`, atrás do proxy HTTPS da Discloud. A mudança só terá efeito depois de integrar a branch e fazer deploy autorizado. O arquivo de produção e o app atual não foram alterados.

## Segurança
- A API exige Authorization `tma <initData>`, valida HMAC usando BOT_TOKEN no servidor e rejeita dados expirados (mais de 24 horas).
- Nunca inserir BOT_TOKEN, ADMIN_IDS ou chaves no JavaScript público.
- Calendário usa o mecanismo atual de check-in diário e sequência DAILY_REWARDS.
- Baú e roleta usam `play_daily_game`, que registra a tentativa e os pontos em transação SQLite e impede segunda tentativa no mesmo dia por jogo.
- Os valores de prêmio são escolhidos no servidor; não confiar em valores enviados pelo navegador.
- As recompensas atuais são simples valores de pontos. Ainda não existe painel para configurar campanhas, períodos, probabilidades ou conteúdo dos eventos.

## Limitações de produto
O calendário desenha o mês, mas o backend atual só tem o estado de check-in atual/sequência, não um histórico mensal completo por data. A ação de coletar reutiliza o check-in diário existente (não cria uma segunda recompensa diária). Para mostrar corretamente todos os dias já coletados será necessária uma tabela histórica aditiva. O evento surpresa ainda funciona como baú diário, não como campanha agendada. A roleta especial reaproveita a tentativa diária da roleta existente.
