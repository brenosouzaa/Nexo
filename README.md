# NEXO Robot Agent — V1

Robô separado do NEXO Operações para sincronizar PDFs de pedidos do TOTVS RM.

## Fluxo oficial

1. O robô permanece na listagem de pedidos do RM.
2. A cada **120 segundos** atualiza a tela.
3. Lê somente os **números dos pedidos**.
4. Pergunta à API do NEXO quais ainda faltam.
5. Para cada pedido faltante, gera o **PDF original do RM**.
6. Envia **número + PDF + SHA-256** ao NEXO.
7. Só marca como concluído após a confirmação da API.
8. O robô não interpreta itens, cliente, validade ou observações; isso pertence ao NEXO.

## Proteções

- comparação RM x NEXO antes de gerar PDF;
- idempotência por número do pedido;
- SHA-256 do PDF;
- histórico local em SQLite;
- recuperação após falhas;
- autenticação por token;
- automação via Windows UI Automation.

## Status

A arquitetura e o ciclo de sincronização já foram implementados. O próximo passo é mapear os controles reais da tela de pedidos do TOTVS RM na VM.
