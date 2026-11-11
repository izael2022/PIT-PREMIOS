# PIT PRÊMIOS

Bot de recompensas para Telegram em Python 3.11+ e SQLite.

## Funcionalidades
- Cadastro e link de indicação, pontos, saldo e ranking.
- Check-in diário, missões, tarefas e jogos de pontos.
- Histórico de créditos e débitos.
- Solicitações de saque com reserva de pontos e análise manual.
- Cadastro Pix criptografado e aprovação manual.
- Backups criptografados, verificados antes do envio e restauração isolada.

## Configuração

Cadastre as variáveis no painel da hospedagem (nunca no GitHub):

| Variável | Obrigatória | Padrão / formato |
|---|---:|---|
| `BOT_TOKEN` | Sim | Token privado obtido no BotFather |
| `ADMIN_IDS` | Sim | IDs numéricos separados por vírgula |
| `DATABASE_PATH` | Não | `data/pit_premios.db` |
| `POINTS_PER_REFERRAL` | Não | `100` |
| `DAILY_REWARDS` | Não | `3,4,5,6,7,8,10` |
| `MIN_REDEEM_POINTS` | Não | `1000` pontos |
| `BACKUP_ENCRYPTION_KEY` | Sim para Pix/backups | Base64 URL-safe de exatamente 32 bytes |
| `MONITOR_HEARTBEAT_URL` | Não | URL HTTPS secreta de monitor externo |

Gere uma chave forte uma única vez e armazene-a como segredo na hospedagem:

```bash
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

**Atenção:** use a mesma `BACKUP_ENCRYPTION_KEY` em todas as reinicializações e restaurações. Não gere uma chave nova a cada deploy. A perda ou rotação sem migração desta chave impede a leitura dos dados Pix e backups anteriores. Nunca envie a chave, token ou arquivos de banco ao GitHub.

Instale as dependências e inicie:

```bash
python -m pip install -r requirements.txt
python main.py
```

## Segurança Pix e saques

- Chaves Pix são cifradas em repouso com AES-GCM; registros novos de saques usam o prefixo de versão `enc:v1:`.
- Registros legados em texto são migrados para cifrado durante a leitura transacional das solicitações.
- A tela do usuário exibe somente chave mascarada. A chave completa só é decifrada para o fluxo administrativo que precisa analisá-la.
- Solicitação reserva pontos; cancelamento e rejeição devolvem os pontos uma única vez; confirmação registra o estado e não debita pontos novamente.
- A confirmação no bot é uma ação administrativa/manual. O bot não executa transferência bancária nem consulta banco/DICT automaticamente.
- A chave de criptografia deve permanecer privada e com backup seguro independente do banco.

## Testes automatizados

O GitHub Actions executa Python 3.11 e 3.12, valida a sintaxe, instala `requirements.txt`, executa os testes de Pix/saques/backup e um teste isolado de concorrência SQLite.

```bash
BOT_TOKEN=123456:test-token ADMIN_IDS=1 BACKUP_ENCRYPTION_KEY=<chave-base64> python -m unittest discover -s tests -v
python scripts/sqlite_load_test.py --workers 4 --writes 500
```

A chave definida no workflow é exclusiva de testes e nunca deve ser reutilizada na hospedagem. Os testes usam banco temporário e não iniciam pagamentos Pix reais.

## Backups e recuperação

O bot cria snapshot SQLite consistente, valida integridade e criptografa o arquivo com AES-GCM antes de enviá-lo aos administradores. A validação do arquivo não substitui o teste periódico de restauração.

Para testar um backup real recebido do bot, em uma máquina/ambiente separado com a mesma chave secreta:

```bash
BACKUP_ENCRYPTION_KEY=<chave-base64> python scripts/verify_backup.py caminho/do/backup.pitbackup
```

O verificador restaura em pasta temporária, confere `integrity_check`, `foreign_key_check` e contagens por tabela, e descarta a cópia ao terminar. Não abre nem modifica `DATABASE_PATH`. Para uma restauração operacional, primeiro pare o bot, faça uma cópia preservando o banco atual e os arquivos WAL/SHM, valide o backup fora da produção e só então planeje a troca com um procedimento de rollback.

## Preservação de dados

O banco de produção padrão permanece em `data/pit_premios.db`. Não apague, recrie ou substitua esse arquivo durante atualização. Faça backup verificado antes de qualquer migração. Os testes automatizados usam exclusivamente um SQLite temporário.

## Limitações

- Saques e pagamentos são analisados manualmente; o bot não realiza pagamentos Pix.
- O teste de carga SQLite é sintético e não representa os limites reais da Discloud.
- A restauração automatizada de CI usa banco de teste. A recuperação de um backup de produção exige arquivo real e a chave secreta correspondente.
