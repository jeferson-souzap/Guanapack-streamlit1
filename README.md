# Guanapack PCP (Streamlit)

Ferramenta do PCP da Guanapack para **montar a programação das extrusoras**: **simulação da programação**
(cenários de fila, ajuste à mão, travas e comparação) e **encaixe em máquinas** dos pedidos sem estoque.
As regras vêm da planilha **Analise-pcp-excel** e do **Guanapack-Flask**.

- Os **relatórios do ERP são lidos direto da pasta** (`.xls`), a cada consulta. Nada é importado.
- O **banco SQLite** (`dados/guanapack.sqlite3`) guarda só o que é do usuário: cadastros, locais da pasta
  por usuário e PC, parâmetros, módulos ativos, cenários salvos e auditoria.

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
| Estoque de pallets | `ESTOQUE_PALLETS.xls` | Reserva (quem fica sem estoque) |
| Controle de pedidos (CTLR) | `CTLR_PEDIDOS.xls` | Data OTD (prazo) |
| Carteira de pedidos (PCP OF) | `PCP_OF_CARTEIRA_PEDIDO.xls` | Reserva, Encaixe |
| Solicitações de reserva | `SOLICITACOES_RESERVA.xls` | CTLR, Reserva |
| Planejamento das máquinas | `PCP_PLANEJAMENTO_GERAL.xls` | Fila atual das máquinas |

Cada relatório é conferido antes do uso: **OK** · **Aviso** (salvo antes de hoje) · **Erro** (falta, não abre ou não é o
relatório certo (o app avisa quando o conteúdo parece ser de outro relatório)). A situação aparece na
Início e na barra lateral.

## Módulos

| Módulo | O que mostra |
|---|---|
| **Início** | Situação dos relatórios e atalhos |
| **Simulação da programação** | Cenários de fila: regras (sequência de formulação, subida e descida de micra, prazo × formulação, setup, OFs fixas), ajuste à mão, travas, desfazer, Gantt e cenários salvos para comparar |
| **Encaixe em máquinas** | Onde produzir os pedidos sem estoque, fila sugerida (com os saltos de micra e a OF de estoque intermediária a gerar) e gráfico de Gantt por máquina |
| **Cadastros** | Rank de formulações, clientes prioritários e regras das máquinas (edição como planilha) |
| **Configuração** | Pasta por usuário/PC, nomes dos arquivos, parâmetros das regras, módulos e backup |

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
| `cenarios_simulacao` | Cenários salvos da simulação (fila, regras, indicadores, escolhido) |
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
| Salto de micra: maior diferença entre duas OFs seguidas | 5 µ |
| Dias de tolerância para relatório antigo | 0 |

## Como funciona o cálculo

```
estoque ─┐
carteira ┼─> reserva da carteira ─────────┐
solicit. ┤                                ├─> encaixe em máquina / simulação da programação
CTLR ────┴─> limpeza do CTLR ─> data OTD ─┤
planej. ───> limpeza ─> extrusão stretch ─┘
```

Cada etapa fica em cache pela "assinatura" dos arquivos (caminho + data de gravação + tamanho), pelos
cadastros e pelos parâmetros de que depende. Salvou um relatório novo? A próxima consulta já usa o novo.
Mudou uma máquina? Só o encaixe é refeito. O botão **Reler relatórios** da
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
  cenarios.py          cenários salvos da simulação
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
