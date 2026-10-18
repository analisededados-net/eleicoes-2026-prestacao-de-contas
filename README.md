# Eleições 2026 - Processamento da prestação de contas

Este guia permite reproduzir localmente as informações de prestação de contas de
Lula e Flávio Bolsonaro apresentadas no site [analisededados](http://localhost:3000/eleicoes/2026/segundo-turno/prestacao-de-contas): incluindo indicadores, distribuições, séries
temporais e rankings de doadores e fornecedores.

Este repo reúne os dados filtrados, os dados processados e **cópias exatas dos scripts
utilizados**. É necessário apenas Python 3, sem instalar dependências externas.
Todos os comandos abaixo devem ser executados a partir desta pasta.

O fluxo foi: **download dos ZIPs no TSE → extração dos dados brutos → filtragem dos
dois candidatos → processamento em JSON para análise**.

## 1. Download e extração dos dados brutos

A primeira etapa foi baixar os arquivos ZIP no **Portal de Dados Abertos do Tribunal
Superior Eleitoral (TSE)**, no conjunto:

[Prestação de Contas Eleitorais — 2026](https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026)

Arquivos baixados:

- `CNPJ_campanha_2026.zip`
- `despesa_documento_2026.zip`
- `extrato_bancario_candidato_2026.zip`
- `extrato_bancario_partido_2026.zip`
- `prestacao_de_contas_eleitorais_candidatos_2026.zip`
- `prestacao_de_contas_eleitorais_orgaos_partidarios_2026.zip`
- `receita_documento_2026.zip`

Após o download, extraia cada ZIP em uma pasta com o mesmo nome, sem a extensão `.zip`,
dentro de um diretório local chamado `0-dados-brutos/`. A estrutura esperada é:

```text
0-dados-brutos/
├── CNPJ_campanha_2026/
├── despesa_documento_2026/
├── extrato_bancario_candidato_2026/
├── extrato_bancario_partido_2026/
├── prestacao_de_contas_eleitorais_candidatos_2026/
├── prestacao_de_contas_eleitorais_orgaos_partidarios_2026/
└── receita_documento_2026/
```

Os CSVs, TXTs e PDFs devem ficar diretamente dentro das respectivas pastas, sem
uma camada adicional de diretórios. `0-dados-brutos/` deve ser criada e preenchida
por quem estiver reproduzindo a análise; os dados brutos não estão incluídos aqui.

Essas pastas contêm os arquivos disponibilizados pelo TSE, incluindo CSVs, cadastros
de CNPJ em TXT e PDFs com os leiautes. Os scripts de transformação **não fazem o
download nem a extração dos ZIPs**: começam a partir dos arquivos já extraídos.

Os dados brutos foram mantidos intactos. Nem todo arquivo baixado entra nos totais:
as contas gerais de órgãos partidários não são atribuíveis exclusivamente a Lula
ou Flávio Bolsonaro e ficaram fora do recorte de titularidade dos candidatos.

As fontes utilizadas nesta execução indicam geração em **18/10/2026**. O conjunto
do portal pode receber atualizações; baixar os ZIPs novamente pode produzir uma
base diferente. Os manifestos permitem conferir a integridade dos arquivos usados
no processamento, mas não constituem hashes dos ZIPs originais.

## Organização desta pasta

- `1-dados-filtrados/`: resultados da filtragem, separados em `lula/` e
  `flavio-bolsonaro/`, mais o `manifesto.json` de seleção e integridade.
- `2-dados-processados/`: JSONs derivados, separados por candidato, além de
  `comparativo.json` e `index.json`.

- `filtrar.py`: dados brutos → CSVs filtrados e cadastro de CNPJ.
- `gerar_json.py`: dados filtrados → JSONs de indicadores, séries, rankings e lançamentos.
  Importa funções de `filtrar.py`; mantenha os dois arquivos juntos.
- `test_filtrar.py` e `test_gerar_json.py`: testes dos dois estágios.
- `proveniencia.json`: caminhos de origem e hashes SHA-256 das cópias, conferidos na criação.

Toda a documentação de reprodução e metodologia está neste README.

Os caminhos absolutos registrados nos manifestos são históricos: refletem os locais
da execução original. Não é necessário reproduzir esses caminhos no seu computador;
os comandos abaixo informam explicitamente as pastas locais de entrada e saída.

## 2. Brutos → filtrados

Execute a filtragem sobre os arquivos extraídos:

```sh
python3 filtrar.py \
  --origem ./0-dados-brutos \
  --destino ./1-dados-filtrados-reproducao
```

O resultado será criado em `1-dados-filtrados-reproducao/`, preservando a pasta
`1-dados-filtrados/` que já acompanha este material. A pasta de destino não pode existir.

Seleciona os dois titulares pelo nome completo, vincula registros sem nome pelo
identificador da prestação e mantém os dados originais apenas em leitura.
Usa os consolidados nacionais `BRASIL`, sem concatenar os recortes estaduais ou `BR`,
para não contar os mesmos registros novamente.

O filtro usa os nomes `LUIZ INACIO LULA DA SILVA` e `FLAVIO NANTES BOLSONARO`,
desconsiderando acentos e caixa, e não uma simples busca por “Lula” ou “Bolsonaro”.
Pagamentos e doadores originários, que não trazem o nome do titular, são vinculados
por `SQ_PRESTADOR_CONTAS`. O cadastro de CNPJ é selecionado pelo CNPJ de campanha.

Os resultados desta etapa estão agora em **`1-dados-filtrados/`**. Os CSVs mantêm
as colunas e valores da fonte, em UTF-8 e com delimitador `;`. O TXT de CNPJ mantém
o leiaute posicional e tem o trailer recalculado para a quantidade selecionada.
Arquivos de documentos sem correspondências contêm apenas o cabeçalho.

Por candidato, são gerados oito arquivos: receitas, despesas contratadas, despesas
pagas, doadores originários, extrato bancário, documentos de receitas, documentos
de despesas e cadastro de CNPJ. As subpastas preservam os caminhos relativos dos
arquivos de origem.

`manifesto.json` registra os critérios, identificadores selecionados, quantidades
por arquivo/candidato/turno e hashes dos arquivos de entrada antes e depois da
filtragem. Transferências de partidos recebidas pelos candidatos continuam nas
próprias receitas; isso não significa incluir as contas gerais desses partidos.

## 3. Filtrados → processados em JSON

```sh
python3 gerar_json.py \
  --origem ./1-dados-filtrados-reproducao \
  --destino ./2-dados-processados-reproducao
```

O resultado será criado em `2-dados-processados-reproducao/`, sem alterar os dados
processados que já acompanham esta pasta. A pasta de destino não pode existir.

Valida os hashes dos filtrados e gera JSONs com valores em centavos inteiros,
datas ISO, indicadores, distribuições, séries diárias/semanais, rankings,
lançamentos e avisos metodológicos. Receitas financeiras e estimáveis são separadas;
extratos e doadores originários não entram nos totais principais.

Os resultados desta etapa estão agora em **`2-dados-processados/`**:

- `index.json`: catálogo, unidades, avisos metodológicos e hashes das saídas.
- `comparativo.json`: resumos dos dois candidatos e fornecedores compartilhados.
- `<candidato>/resumo.json`: indicadores e distribuições de receitas e despesas.
- `<candidato>/series.json`: séries diárias, semanais e acumuladas.
- `<candidato>/rankings.json`: doadores e fornecedores, com concentração dos valores.
- `<candidato>/receitas.json`, `contratadas.json` e `pagamentos.json`: lançamentos
  normalizados, com referência à linha do CSV filtrado.
- `<candidato>/doadores_originarios.json` e `extratos.json`: dados auxiliares,
  separados dos totais principais.
- `<candidato>/documentos_receitas.json` e `documentos_despesas.json`: registros
  de documentos; nesta execução, as listas estão vazias por ausência na fonte filtrada.

Datas usam `YYYY-MM-DD`; valores monetários usam **centavos inteiros**; identificadores
continuam como texto. Para apresentar um valor em reais, divide-se por 100 somente
na formatação. Dados ausentes usam `null`. Percentuais são números de 0 a 100,
ou `null` quando o denominador é zero.

### Como os resultados são calculados

- **Indicadores:** somas dos lançamentos selecionados, mantendo receitas financeiras,
  receitas estimáveis, despesas contratadas e pagamentos como medidas distintas.
- **Distribuições:** agrupamento pelas categorias declaradas na fonte, como origem,
  fonte e natureza da receita ou categoria da despesa; cada percentual usa o total
  da respectiva medida e candidato.
- **Séries:** agrupamento pela data de cada lançamento, com valores no período e
  acumulados. As semanas começam na segunda-feira. Intervalos sem lançamentos,
  entre a primeira e a última data disponível, recebem zero. Valores sem data
  ficam contabilizados à parte, sem atribuição artificial a um dia.
- **Rankings:** agrupamento dos valores por doador ou fornecedor, com a quantidade
  distinta e a participação dos dez maiores no total da medida. Doadores imediatos,
  doadores financeiros e doadores originários são apresentados separadamente.
- **Fornecedores compartilhados:** identificação dos fornecedores com despesas
  contratadas nos dois candidatos; isso não demonstra irregularidade ou vínculo político.
- **Vínculos:** os identificadores permitem conferir pagamentos contra despesas e
  doadores originários contra receitas. Não se multiplicam pagamentos pelo número
  de itens de uma mesma despesa.

### Cuidados de interpretação

- Os totais são declarados e provisórios, não uma auditoria ou aprovação das contas.
- Itens distintos podem compartilhar o mesmo identificador de receita ou despesa.
  Por isso, não se eliminam linhas apenas por esses identificadores.
- Mesmo repetições exatas são preservadas e sinalizadas nos relatórios de qualidade.
  O campo `qualidade.<dataset>.repeticoes_exatas_preservadas` informa sua quantidade.
- Não se somam despesas contratadas com despesas pagas, nem extratos com receitas.
- Doadores originários detalham receitas existentes; não representam uma segunda arrecadação.
- A diferença entre contratado e pago não é automaticamente dívida ou saldo bancário.
- O turno declarado identifica a prestação, não necessariamente o período de cada
  lançamento. Mantêm-se todos os lançamentos disponíveis nas prestações selecionadas.
- O gerador interrompe se encontrar mais de uma combinação de prestador, turno,
  tipo ou data de prestação por candidato. Não escolhe automaticamente entre
  parciais, finais ou retificadoras que possam repetir valores cumulativos. Nos
  dados incluídos há uma prestação por candidato, ambas com turno declarado 2.
- Os JSONs não publicam CPF/CNPJ ou dados de contas bancárias. Nomes são mantidos e
  as chaves de agrupamento usam hashes; isso é pseudonimização, não anonimização.

### Integridade e interrupções

Os arquivos de entrada são abertos somente para leitura. Os scripts recusam destinos
existentes, evitando sobrescritas e mistura de execuções. Uma execução interrompida
pode deixar uma pasta parcial sem manifesto de conclusão; nesse caso, escolha
outro destino para reexecutar.

Se os arquivos de documentos passarem a conter registros, o gerador exige uma
implementação específica para convertê-los antes de prosseguir, em vez de descartá-los
silenciosamente. Os resultados incluídos aqui não têm esses registros.

## Atalho: reproduzir a partir dos filtrados incluídos

Para gerar as informações sem baixar e filtrar novamente os arquivos do TSE, use
os dados já disponíveis em `1-dados-filtrados/`:

```sh
python3 gerar_json.py \
  --origem ./1-dados-filtrados \
  --destino ./2-dados-processados-reprocessamento
```

Os scripts preservam os caminhos padrão da execução original. Por isso, **use sempre
`--origem` e `--destino`**, como nos exemplos, para trabalhar com suas pastas locais.
Se o destino escolhido já existir, escolha um nome novo. Não é necessário apagar
ou sobrescrever resultados anteriores.

## Consultar e conferir os resultados

Abra os JSONs de saída com um editor ou com Python. Por exemplo, para consultar os
indicadores de Lula na reprodução completa:

```sh
python3 -m json.tool ./2-dados-processados-reproducao/lula/resumo.json
```

Use `comparativo.json` para comparar os candidatos, `series.json` para acompanhar
os valores ao longo do tempo e `rankings.json` para consultar os maiores doadores
e fornecedores. Os arquivos de lançamentos permitem examinar os registros que
compõem os indicadores.

O filtro compara hashes dos arquivos de entrada antes e depois da execução. O
processamento verifica os filtrados contra `manifesto.json` e registra os hashes
dos JSONs em `index.json`. Datas de execução e caminhos podem variar entre
reproduções; para obter os mesmos indicadores, é necessário usar a mesma versão
dos dados do TSE e os mesmos scripts.

## Testes

```sh
python3 -m unittest discover -s . -v
```

Os testes usam fixtures temporárias; não reprocessam nem modificam as bases reais.
