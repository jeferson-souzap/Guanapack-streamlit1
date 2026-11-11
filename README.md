# Guanapack PCP (Streamlit)

App do PCP da Guanapack que leva para o navegador tudo o que foi feito na planilha **Analise-pcp-excel**
(rev025–027) e no **Guanapack-Flask**: atraso OTD, reserva da carteira, encaixe em máquinas, tubetes e
pallets e troca de embarque. É organizado em **módulos** e tem uma **Início** simples.

- Os **relatórios do ERP são lidos direto da pasta** (`.xls`), a cada consulta. Nada é importado.
- O **banco SQLite** (`dados/guanapack.sqlite3`) guarda só o que é do usuário: cadastros, locais da pasta
  por usuário e PC, parâmetros, módulos ativos, histórico, anotações e auditoria.

## Como abrir

Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o ambiente (`.venv`) e instala as
dependências. Depois abre `http://localhost:8501`.

Pelo terminal:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

Testes das regras: `.venv\Scripts\python.exe -m pytest -q`

## Relatórios usados

Salve os relatórios do ERP na pasta configurada (nomes padrão, que podem ser trocados em
Configuração > Arquivos):

| Relatório | Arquivo padrão | Usado em |
|---|---|---|
| Estoque de pallets | `ESTOQUE_PALLETS.xls` | Estoque, Reserva |
| Controle de pedidos (CTLR) | `CTLR_PEDIDOS.xls` | Pedidos e OTD, Troca |
| Carteira de pedidos (PCP OF) | `PCP_OF_CARTEIRA_PEDIDO.xls` | Reserva, Encaixe, Insumos |
| Solicitações de reserva | `SOLICITACOES_RESERVA.xls` | CTLR, Reserva |
| Planejamento das máquinas | `PCP_PLANEJAMENTO_GERAL.xls` | OTD (exportação), Encaixe, Máquinas, Insumos |

Cada relatório é conferido antes do uso: **OK** · **Aviso** (salvo antes de hoje) · **Erro** (falta, não abre ou não é o
relatório certo (o app avisa quando o conteúdo parece ser de outro relatório)). A situação aparece na
Início e na barra lateral.

## Módulos

| Módulo | O que mostra |
|---|---|
| **Início** | Situação dos relatórios, botão **Atualizar tudo** e o resumo do dia |
| **Consulta de pedido** | Tudo sobre um pedido (CTLR, reserva, encaixe, planejamento, troca) e **anotações** |
| **Pedidos e OTD** | Atrasados e que vão atrasar pela data OTD (embarque − N dias; exportação pela data do planejamento) |
| **Estoque** | Disponível, dias parado, slow move, por formulação |
| **Reserva da carteira** | Pallet sugerido para cada pedido (exato ou alternativo) e motivo de quem fica sem estoque |
| **Encaixe em máquinas** | Onde produzir os pedidos sem estoque, fila sugerida e gráfico de Gantt por máquina |
| **Planejamento das máquinas** | Cada OF com a reserva do mesmo pedido |
| **Tubetes e pallets** | Consumo das OFs abertas, sem e com os encaixes novos |
| **Troca de embarque** | Pedidos emitidos ontem/hoje que precisam de nova data, com texto pronto para o comercial |
| **Histórico** | Evolução dos indicadores, log de execuções e auditoria dos cadastros |
| **Cadastros** | Rank de formulações, clientes prioritários e regras das máquinas (edição como planilha) |
| **Configuração** | Pasta por usuário/PC, nomes dos arquivos, parâmetros das regras, módulos e backup |

Todas as tabelas têm busca e botão **Excel**. Em Configuração > Módulos dá para desligar módulos e
mudar a ordem do menu (Início, Cadastros e Configuração ficam sempre ligados).

## O que fica no banco

| Tabela | Conteúdo |
|---|---|
| `formulacoes` | Rank de formulações (menor = mais simples; o alternativo da reserva pode subir N degraus) |
| `clientes_prioritarios` | Clientes especiais que não podem atrasar (parte do nome + material/formulação opcionais) |
| `maquinas` | Regras de cada extrusora: formulações, o que não roda, faixas de micra, peso, tubete e largura |
| `locais_relatorios` | Pasta dos relatórios por usuário e PC (`*` = qualquer) |
| `arquivos_relatorios` | Nome do arquivo de cada relatório |
| `parametros` | Parâmetros das regras alterados (os padrões estão em `config.py`) |
| `modulos`, `preferencias` | Módulos ativos/ordem e preferências por usuário |
| `historico_indicadores` | Um retrato dos números a cada **Atualizar tudo** |
| `execucoes` | Log de quem rodou o quê, quando e quanto demorou |
| `anotacoes` | Anotações livres nos pedidos (resolver/reabrir) |
| `auditoria` | Toda alteração em cadastros, locais e parâmetros: antes, depois, usuário e PC |

Na primeira execução os cadastros são carregados dos CSV em `cadastros/` (só com a tabela vazia).
Um **backup automático** do banco é feito por dia em `dados/backup/` (ficam os 30 mais novos); em
Configuração > Banco dá para fazer backup na hora ou baixar o banco.

### Qual pasta é usada

Do mais específico para o mais geral:

1. variável de ambiente `PCP_REPORTS_DIR` (útil para testar com outra pasta);
2. salva para **você neste PC**;
3. salva para **qualquer usuário neste PC**;
4. salva para **você em qualquer PC**;
5. **local geral**;
6. `config.PASTA_PADRAO`.

## Parâmetros das regras

Editáveis em Configuração > Parâmetros (padrões da planilha rev027):

| Parâmetro | Padrão |
|---|---|
| Data OTD = embarque − N dias | 2 |
| Tolerância da reserva sobre o qtde_kg | ±5% |
| Micra aceita no alternativo | ±2 |
| Degraus que o alternativo pode subir no rank | 1 |
| Primeiras OFs fixas de cada máquina no encaixe | 3 |
| Dias para slow move | 90 |
| Dias de tolerância para relatório antigo | 0 |

## Como funciona o cálculo

```
estoque ─┐                         ┌─> encaixe em máquina ─┬─> tubetes e pallets
carteira ┼─> reserva da carteira ──┘                       └─> troca de embarque
solicit. ┤                               ▲
CTLR ────┴─> limpeza do CTLR ─> atraso OTD (data OTD)
planej. ───> limpeza ─> extrusão stretch ┘
```

Cada etapa fica em cache pela "assinatura" dos arquivos (caminho + data de gravação + tamanho), pelos
cadastros e pelos parâmetros de que depende. Salvou um relatório novo? A próxima consulta já usa o novo.
Mudou uma máquina? Só o encaixe, os insumos e a troca são refeitos. O botão **Reler relatórios** da
barra lateral apaga o cache.

As regras (`core/regras/`) são as mesmas do Guanapack-Flask, conferidas com a planilha Excel, e têm
testes em `tests/`.

## Estrutura

```
app.py                 entrada: banco, menu dos módulos e barra lateral
config.py              relatórios, parâmetros e padrões
iniciar.bat            atalho para abrir o app
core/
  db.py                banco SQLite (esquema, carga inicial, auditoria, backup)
  contexto.py          usuário/PC, pasta dos relatórios, parâmetros, módulos
  relatorios.py        leitura e conferência dos .xls (com cache)
  pipeline.py          cadeia de cálculo em memória (com cache por etapa)
  cadastros.py         validação e gravação dos cadastros
  indicadores.py       números do painel e histórico
  anotacoes.py         anotações nos pedidos
  ui.py                peças de tela (tabela com busca, Excel, avisos)
  regras/              regras de negócio (puras, testadas)
modulos/               uma página por módulo (registro em modulos/__init__.py)
cadastros/             CSV da carga inicial
dados/                 banco e backups (criado na primeira execução)
tests/                 testes das regras (pytest)
```

### Criar um módulo novo

1. Crie `modulos/meu_modulo.py` usando `ui.ctx()` para pegar os dados (`c.reserva()`, `c.encaixe()`…).
2. Inclua uma linha em `MODULOS` em `modulos/__init__.py`.
