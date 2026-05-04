# CDR Genesys Cloud — Dashboard

## Configuração

Abra o arquivo `app.py` e edite as duas linhas no topo:

```python
GENESYS_REGION = "mypurecloud.com"   # sua região Genesys
OAUTH_TOKEN    = "SEU_TOKEN_AQUI"    # token OAuth gerado
```

### Regiões comuns
| Região        | Valor                        |
|---------------|------------------------------|
| EUA (Oregon)  | `mypurecloud.com`            |
| Brasil        | `mypurecloud.com.br`         |
| EUA Leste     | `use2.us-east-2.pure.cloud`  |
| Europa        | `mypurecloud.de`             |
| Austrália     | `mypurecloud.com.au`         |

### Permissões necessárias no token OAuth
```
analytics:conversationDetail:view
routing:flow:view
```

## Como rodar

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Iniciar
python app.py
```

Acesse: `http://localhost:5051`

## Funcionalidades

- Lista todos os fluxos disponíveis automaticamente no filtro
- Filtra CDRs por **fluxo**, **período** e **direção** (Receptivo / Ativo)
- Paginação de 50 registros por página
- Cards de resumo: Total, Receptivo, Ativo, Com Agente, Apenas Bot
- Campos exibidos por CDR:
  - Conversa ID, Início, Fim, Duração total
  - Direção (badge colorido)
  - ANI e DNIS formatados como telefone
  - Nome do fluxo e tipo
  - Fila, Agente
  - Tempo de fala, Espera, Tipo de desconexão
- Rate limit local: máx. 10 req/min com barra visual no cabeçalho
- Alerta a cada 10 bloqueios acumulados
- Atualização automática a cada 20 minutos
- Controle de erros HTTP: 401, 403, 404, 429, 5xx, timeout, conexão

### Em desenvolvimento:
- CDR Analytics
- Filtros avançados
- Exportação de dados
- Gráficos e visualizações
- Acompanhamento dos milestones
- Rastrear milestones específicos
- Entre outros...