# Auditoria inicial — decidir se o TinyLLM serve para uma demo

O relatório é **offline**. Não instala dependências, não usa Codex, não altera o SQLite e não toma decisões de aceitação/rejeição.

## Executar

```bash
git pull --ff-only
python -m unittest -v
python auditar_dataset.py --per-cell 2 --seed 42
```

Amostra de até 70 conversas: 2 por cada uma das 35 combinações das 5 personas e 7 capacidades.

## Resultados

- `dados/auditoria/resumo.json`: número de conversas, receitas distintas, cobertura e avisos mecânicos.
- `dados/auditoria/amostra_para_revisao.md`: conversas completas, fonte, citações e grelha para avaliação humana.
- `dados/auditoria/amostra.jsonl`: as mesmas conversas em formato para análise.

Para uma revisão rápida com menos texto:

```bash
python auditar_dataset.py --per-cell 1
```

O relatório será substituído por uma amostra de até 35 conversas.

## Como decidir se serve para demonstração

Avaliar cada exemplo em cinco dimensões, de 0 a 2 pontos: fidelidade factual à receita, utilidade, naturalidade, persona e capacidade demonstrada. A lista de alertas é um filtro mecânico, **não** uma nota de qualidade.

Condições sugeridas para avançar para uma demo interna: revisão de pelo menos 35 exemplos, sem erros factuais graves, boa diversidade de comportamentos e conversas C6 com verdadeira continuidade. Exemplos com ingredientes, tempos ou medidas inventados não devem ser usados como demonstração de respostas fiáveis.

O dataset é, por enquanto, **inglês**. Uma demo em português exigirá dados e/ou treino adequados. O relatório **não** avalia diretamente os pesos ou as respostas do modelo estudante: isso requer treino ou carregamento do modelo e um conjunto de prompts de teste separados das receitas de treino.

Não usar `auto_valid` como sinónimo de verdade factual e não usar exemplos do treino como avaliação de generalização.
