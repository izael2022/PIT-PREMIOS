# PIT PRÊMIOS — Pacote de sistemas e integração

Branch: `auditoria-correcao-integral-pit-premios`

Este plano é a trilha única para integração do conjunto de módulos. Implementar incrementalmente em commits agrupados, preservando banco de produção e saldo.

## Módulos / estado inicial

- [x] Infraestrutura de campanhas genéricas (tipos calendar/event/surprise/challenge/collective_goal/special_mission) — engine existente em systems_extra.py; confirmar UX final e integração completa.
- [x] Conquistas e resgates únicos — engine existente; auditar UX/admin.
- [x] Temporadas/ranking — engine existente; auditar UX/admin.
- [ ] Calendário mensal: apresentação por datas, regras de resgate, limites por dia, painel admin.
- [ ] Evento surpresa: ativação programada, janela de exibição e resgate idempotente.
- [ ] Central de notificações: avisos persistentes, leitura/expiração e admin.
- [ ] Desafios: individual, metas e prazos; validar progresso com eventos existentes sem criar créditos duplicados.
- [ ] Indicações: regras/marcos, antifraude e auditoria de cálculo.
- [ ] Loja: catálogo, reserva/consumo de pontos e proteção contra replay.
- [ ] Ranking/temporadas: tela de usuário, administração, critérios, desempates e encerramento.
- [ ] Painel unificado: controles de ativação, edição, agendamento, métricas e logs.
- [ ] Integração com menus/callbacks Telegram; controle de acesso admin e bloqueados.
- [ ] Testes de regressão, SQLite temporário, compatibilidade e verificação CI.

## Pacote adicional iniciado (commits da auditoria)
- [x] Engine aditiva de tickets de suporte (abertura, listagem, resposta e fechamento), com testes isolados.
- [x] Limites configuráveis por escopo e consumo transacional por período, com testes.
- [x] Revisões antifraude centralizadas (registro e decisão), com testes.
- [x] XP e níveis derivados (sem alteração de carteira), com testes.
- [x] Medalhas/conquistas (cadastro e concessão idempotente), com testes.
- [x] Avisos programados com janela de publicação, com testes.
- [x] Logs administrativos aditivos, com testes.
- [x] Notificações novas com expiração e leitura, com testes.
- [x] Consultas de calendário mensal e janela de evento surpresa.
- [ ] Integrar todos estes novos endpoints às telas/callbacks do bot, persistência do banco operacional e painel admin.
- [ ] Histórico financeiro unificado na interface (usar ledger existente, sem duplicar ou alterar dados).
- [ ] Antifraude automatizado: sinais e revisão; não aplicar bloqueios automáticos sem regras verificadas.
- [ ] Testar a integração completa no bot e CI antes de marcar pacote como pronto para produção.

## Regras obrigatórias
- Não apagar, recriar ou migrar destrutivamente o DB de produção.
- Nenhum saldo/ponto deve ser creditado fora de transação e registro de ledger existente.
- Callback deve validar autorização, ID, status, janela e idempotência.
- Não alegar deploy/CI aprovado sem resultado observado.
- Desativação de módulos deve ser reversível; migrations aditivas.
- Revisar operações de escrita e replay de update_id antes de lançamento.

## Sequência de integração do pacote
1. Inventário de UX/menu/callbacks e esquema existente, mapear os módulos já implementados para não duplicar.
2. Calendário + eventos surpresa usando engine de campanhas.
3. Central de notificações persistente.
4. Desafios e progresso (eventos de progresso integrados com idempotência).
5. Indicações (auditoria antifraude).
6. Loja (transação, reserva, replay e histórico).
7. Ranking/temporadas e encerramento.
8. Painel admin unificado, menus/callbacks.
9. Testes de integração isolados, CI e relatório final.
