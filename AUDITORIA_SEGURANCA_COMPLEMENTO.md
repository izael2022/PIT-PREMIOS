# Complemento de segurança e resiliência — PIT PRÊMIOS

## Alterações desta rodada

- Comandos e botões do participante passam a ser recusados em grupos; o usuário é orientado a abrir o privado. O comando /start em grupos não cadastra nem exibe carteira.
- A solicitação de saque valida o formato básico da chave Pix de acordo com o tipo: dígitos verificadores de CPF/CNPJ, formato de e-mail, quantidade de dígitos de telefone e UUID para chave aleatória.
- Falhas inesperadas no processamento deixam de ser silenciosamente confirmadas. O processamento tenta novamente até três vezes com espera progressiva; se continuar falhando, a atualização não é marcada como concluída e permanece na fila durável para recuperação na próxima inicialização.
- O backup automático tenta novamente após falhas em 5 minutos, 15 minutos, 1 hora e, depois, a cada 6 horas, até ter sucesso. Após sucesso, mantém a periodicidade diária.
- A autenticação inicial com getMe agora usa reconexão progressiva, evitando encerrar o processo por uma indisponibilidade temporária do Telegram.
- Teste de banco de dados maior mede o pico de alocação Python durante a criação/validação do backup.

## Proteção dos dados

As alterações foram feitas no código e em testes isolados. Nenhuma rotina de migração foi adicionada e nenhum arquivo de banco de produção foi lido, modificado, substituído ou apagado.

## Limites e validações ainda necessárias

- A validação local de chave Pix verifica formato e dígitos verificadores; não confirma titularidade, existência ou situação da chave junto ao DICT/PSP.
- O teste de memória usa tracemalloc em runner do GitHub Actions e um banco sintético de 4 MiB. Ele não representa o limite real de RAM da Discloud nem substitui teste de carga com uma cópia anonimizada do banco real.
- Se uma atualização falhar nas três tentativas, ela fica pendente durável e será recuperada na próxima inicialização. O bot alerta pela fila durável/monitoramento; não executa loop infinito de repetição em tempo real.
- A aprovação de saque continua sendo uma confirmação manual do administrador; o bot não realiza transferência Pix.
- A atualização da Discloud não faz parte desta alteração. O deploy deve ocorrer somente após revisão do PR e confirmação de que o arquivo data/pit_premios.db não está no pacote de código.
