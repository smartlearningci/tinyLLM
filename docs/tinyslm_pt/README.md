# TinySLM — Receitas em português (Portugal + Brasil)

Este módulo prepara uma **base SQLite** de receitas em português para o TinySLM. O objetivo é facilitar a consulta, a revisão e, mais tarde, a criação de exemplos de treino. Não altera o corpus inglês nem inicia o treino do modelo.

## Abrir a base de receitas (3 comandos)

No terminal, na pasta do repositório `tinyLLM`:

```bash
git pull --ff-only
python tools/tinyslm_pt/criar_bd_pt.py
python tools/tinyslm_pt/ver_bd_pt.py
```

Abre **http://127.0.0.1:8767** no navegador.

Na página podes pesquisar `bolo`, `arroz`, `panquecas`, filtrar por origem e estado, abrir os ingredientes, consultar a preparação e ver as técnicas e as alternativas gerais.

A primeira execução de `criar_bd_pt.py` descarrega automaticamente os dois conjuntos de dados públicos indicados abaixo e guarda:

- `dados/fontes/receitas_wikilivros.jsonl` — fonte original estruturada;
- `dados/fontes/afrodite.json` — fonte original estruturada;
- `dados/tiny_pt.sqlite` — base unificada;
- `dados/tiny_pt.relatorio.json` — contagem e estados.

As pastas `dados/` já são ignoradas pelo Git: **não se apagam nem se alteram as bases anteriores**. Se `tiny_pt.sqlite` já existir, o programa não a substitui. Para reconstruir, escolhe outro nome, por exemplo:

```bash
python tools/tinyslm_pt/criar_bd_pt.py --saida dados/tiny_pt_v2.sqlite
python tools/tinyslm_pt/ver_bd_pt.py --bd dados/tiny_pt_v2.sqlite
```

Se não houver ligação à internet no computador de trabalho, os ficheiros de origem podem ser fornecidos manualmente:

```bash
python tools/tinyslm_pt/criar_bd_pt.py \
  --wikilivros /caminho/receitas.jsonl \
  --afrodite /caminho/afrodite.json
```

O código usa **apenas Python 3.10+**, sem instalar bibliotecas externas.

## O que a base contém

| Tabela | Informação |
|---|---|
| `receitas` | ID, título, origem, idioma, estado, possível duplicado, grupo de receitas, registo original |
| `partes` | Ingredientes, preparação e informação adicional, em registos separados |
| `apoio` | 12 técnicas culinárias e 8 substituições genéricas, **não validadas para receitas concretas** |

Estados: `completa` (pelo menos dois ingredientes e uma instrução); `parcial` (há informação mas faltam campos estruturados); `incompleta` (sem informação aproveitável nos campos analisados). **Completa não significa receita validada.**

Os originais ficam guardados dentro de `receitas.original_json`, para recuperar mais informação sem perder texto. Não se inventam ingredientes nem quantidades. Duplicados exatos são assinalados, mas não eliminados; receitas com o mesmo título têm um `grupo` para ajudar a separar treino/teste. Ainda pode haver variantes e duplicados não identificados.

### Fontes

- **Wikilivros / Cozinheiro Artificial** — [repositório com 2.506 receitas](https://github.com/denisevitoriano/tech_challenge_fase_04/tree/main/data/processed). Português de origem mista; não presumimos que tudo é português de Portugal.
- **Afrodite** — [repositório com 8.183 registos brasileiros](https://github.com/adrianosferreira/afrodite.json).

Verificação dos dados consultados em 24/11/2026: **10.689 registos**, dos quais **3.543** tinham simultaneamente ingredientes e preparação preenchidos nas secções principais. Muitos registos da Afrodite têm listas vazias e/ou informação noutras secções. O importador conserva esses casos, em vez de os declarar receitas validadas.

A fonte académica portuguesa referida anteriormente tem sobretudo identificação de pratos, sem preparação e quantidades suficientes para este assistente, pelo que não foi importada como se fosse uma receita completa.

## Consultar pelo terminal (opcional)

Ver quantas receitas existem:

```bash
python tools/tinyslm_pt/consultar_bd_pt.py
```

Procurar receitas por nome e obter um ID real:

```bash
python tools/tinyslm_pt/consultar_bd_pt.py --listar --termo "bolo de cenoura"
```

Depois copia o campo `id` de uma receita e usa-o em vez de `ID_DA_RECEITA`:

```bash
python tools/tinyslm_pt/consultar_bd_pt.py \
  --receita-id ID_DA_RECEITA --tipo ingrediente --termo "açúcar"

python tools/tinyslm_pt/consultar_bd_pt.py \
  --receita-id ID_DA_RECEITA --tipo preparo --termo "forno"

python tools/tinyslm_pt/consultar_bd_pt.py \
  --receita-id ID_DA_RECEITA --tipo alternativa --termo "açúcar" --para "sacarina"

python tools/tinyslm_pt/consultar_bd_pt.py --tipo tecnica --termo "refogar"
```

**Importante:** se a alternativa específica não estiver registada, a ferramenta responde `SEM_ALTERNATIVA_REGISTADA`. Não afirma que a substituição é impossível; apenas que não consta dos dados. As 8 alternativas existentes são gerais e condicionais.

## Exportar receitas preparadas para revisão e treino

```bash
python tools/tinyslm_pt/exportar_bd_pt.py
```

Cria `dados/receitas_pt_normalizadas.jsonl` com receitas estruturadas completas e sem os duplicados exatos detetados. Não constitui ainda um dataset de conversas supervisionadas nem prova de qualidade culinária.

Para exportar todos os registos, incluindo os parciais:

```bash
python tools/tinyslm_pt/exportar_bd_pt.py --todas --saida dados/receitas_pt_todas.jsonl
```

Os ficheiros de origem, SQLite e JSONL são **gerados no computador do utilizador**, não colocados diretamente no GitHub. O repositório guarda o código, os testes, o glossário inicial e as instruções para reconstruir os dados. Isto mantém o repositório leve e evita publicar automaticamente todo o conteúdo das fontes de terceiros.

## Testar sem descarregar dados

```bash
python -m unittest discover -s tools/tinyslm_pt -p 'test_*.py' -v
```

## Próximos passos do TinySLM

Antes do treino massivo: rever a qualidade das receitas, enriquecer uma seleção de técnicas/substituições com relações efetivamente válidas para cada receita, criar exemplos em PT-PT e PT-BR no formato mínimo **pergunta → chamada simples → dado → resposta** e medir o tokenizer real para assegurar os **512 tokens**. A ferramenta atual de consulta **não está ligada ao LLM** e ainda não faz recuperação inteligente de excertos longos.