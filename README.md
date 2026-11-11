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

## Verificações operacionais (sem tocar no banco ativo)

### Testar restauração de um backup
Baixe o arquivo `.pitbackup` enviado pelo bot e execute em um computador confiável com a mesma `BACKUP_ENCRYPTION_KEY` configurada na hospedagem:

```bash
python scripts/verify_backup.py caminho/do/backup.pitbackup
```

O script descriptografa e restaura somente em uma pasta temporária, executa `integrity_check` e `foreign_key_check`, lista tabelas e quantidades e descarta a cópia temporária. Não sobrescreve arquivos existentes nem abre `DATABASE_PATH`.

### Teste isolado de concorrência SQLite

```bash
python scripts/sqlite_load_test.py --workers 4 --writes 500
```

Esse benchmark cria um banco temporário, executa transações concorrentes e verifica o resultado. Ele ajuda a comparar mudanças de código, mas **não representa um teste de carga real da Discloud**.

### Monitor externo
Configure `MONITOR_HEARTBEAT_URL` no painel da hospedagem com a URL HTTPS secreta fornecida por um monitor de heartbeat (por exemplo, Better Stack). O bot envia o ping após cada ciclo de saúde bem-sucedido. Mantenha a URL somente nas variáveis de ambiente, nunca no GitHub. O painel administrativo passa a indicar se o heartbeat está configurado e alerta quando não há backup bem-sucedido registrado ou quando o último registro passa de 30 horas.

O registro de backup confirma que o arquivo foi criado, validado e enviado a pelo menos um administrador; o teste de restauração manual continua necessário para comprovar recuperação ponta a ponta.


## Cadastro de chave Pix do usuário

- O participante cadastra o tipo da chave (CPF, CNPJ, e-mail, telefone ou aleatória) e informa o nome do titular.
- A chave fica criptografada em repouso com AES-GCM, usando a variável secreta `BACKUP_ENCRYPTION_KEY` já utilizada pelo sistema de backups. Mantenha essa chave estável: perdê-la impede a leitura dos cadastros Pix criptografados.
- O cadastro fica pendente até a aprovação/reprovação manual por um administrador.
- Somente cadastros aprovados podem ser usados em novas solicitações de saque.
- Os pagamentos continuam manuais. O bot não consulta automaticamente o DICT nem confirma a titularidade via Mercado Pago.
- A tabela `pix_profiles` e o estado temporário `pix_setup_state` são criados com `CREATE TABLE IF NOT EXISTS`; não removem nem redefinem dados existentes.
