# TinySLM — histórico, factos e mudança de estratégia

Estado de referência: 22/11/2026. Este documento regista o que foi **observado**,
separadamente do que é uma proposta ou de algo que está apenas preparado.

## Objetivo

Construir um modelo culinário pequeno (~51 milhões de parâmetros), que possa
funcionar com recursos modestos. O modelo responde diretamente ao que realmente
consegue fazer (C1) e aprende a pedir ferramentas para o que exige evidência ou
operações adicionais (inicialmente C2). A receita ativa é **sempre conhecida
pela aplicação**, que conserva o `recipe_id`.

## Como aqui chegámos

1. **Corpus inicial e modelos de base (agosto–setembro de 2026).** O primeiro
   corpus de PT incluía 1.206 documentos aceites e cerca de 363 mil tokens.
   Um modelo experimental de aproximadamente 8M parâmetros gerava texto
   insuficiente para a aplicação culinária. Evoluímos para uma base de ~51M
   parâmetros, tokenizer de ~8k tokens e contexto máximo de 512 tokens.
   O modelo de base demonstrava fluência local, mas tinha limitações de
   conhecimento, instruções e raciocínio.
2. **Receitas e respostas do teacher.** O catálogo histórico de destilação
   mencionava **5.108 receitas** em `dados/queue.sqlite` (fotografia de
   12–14/11). Para a experimentação de intenções e recuperação de receitas,
   está disponível uma base separada de **5.025 receitas** provenientes de
   `recipe_nlg_lite`, e **138.794 perguntas/respostas** históricas C1–C7.
   A diferença de 83 receitas **não está resolvida**. As respostas geradas
   por teacher não devem ser tratadas como verdade apenas por terem citação.
3. **Intenções v09.** Foram treinadas duas épocas com 17.783 exemplos de
   intenções e 1.432 exemplos de manutenção de receitas (19.215 no total).
   O teste registou 93,08% de correspondência exata com um teacher **não
   verificado** em 1.012 exemplos, mas apenas **8/15 (53,33%)** em perguntas
   fora do domínio revistas pelo assistente. A `recipe_validation_loss`
   piorou de 1,54706 para 1,58549. Este treino classificava intenções;
   **não** ensinava o ciclo real de chamada + resultado + resposta.
4. **Experiência v11.** Um piloto pequeno para decisão e resposta com
   ferramenta obteve **0% nas métricas de correspondência estrita** do teste
   de 100 casos (50 tool/50 direct). Sem as previsões individuais não é
   possível separar erros do modelo de problemas do avaliador/protocolo.
   O resultado não valida a capacidade end-to-end.
5. **Reconstrução v12.** Normalizámos mecanicamente as 5.025 receitas
   disponíveis, preservando os originais. Encontrámos **3.248 receitas com
   avisos de parsing**. Das 138.794 perguntas/respostas, 138.654 possuíam
   citação literal na receita; a recuperação por ferramenta encontrou
   evidência candidata para 82.325, deixando **56.329 para reparação**.
   Foram preparados 66.743 exemplos de treino, 7.294 de validação e 8.288
   de teste por receita. Em C2, só 5.102/18.524 exemplos passaram o filtro
   de evidência, pelo que a pesquisa necessita de melhoria.
   **O treino massivo v12 foi preparado, não executado nem validado.**

## Diagnóstico acordado

- Um modelo de 51M não deve gastar capacidade a aprender esquemas JSON
  extensos ou operações que podem ser efetuadas por software determinístico.
- O formato que o modelo vê deve ser **linguagem natural estruturada e
  previsível**, tanto nas receitas como nos pedidos/resultados de ferramentas.
- **C1 é a capacidade com melhor evidência histórica**, mas há que medir
  novamente em testes independentes após qualquer fine-tuning.
- **C2–C7 não estão demonstradas** de ponta a ponta. Concentrar o MVP em
  C1 direto e C2 com `RECIPE_SEARCH`. Só depois estender às restantes.
- Não basta o modelo produzir `CALL TOOL`: o resultado da pesquisa deve ser
  correto e a resposta deve apoiar-se na evidência.
- O conjunto de dados pode ser grande; a qualidade de exemplos e a separação
  por receita são obrigatórias, evitando memorizar as receitas de teste.
- Perguntas fora do domínio e perguntas sem evidência são testes próprios;
  não declarar segurança ou rejeição robusta sem prova.

## Limitações da auditoria histórica

- Contar citações literais não certifica respostas factual ou semanticamente.
- `PREPARATION SEGMENTS` v12 resulta da pontuação; não equivale sempre a
  passos culinários completos e revistos.
- A fonte `recipe_nlg_lite` desta SQLite está em inglês. A normalização
  **não traduz** nem inventa conteúdo; treino de diálogo em português
  exige plano/dados próprios, a decidir após o MVP.
- A execução deste documento não implica iniciar novos treinos Kaggle.

## Proveniência

- Base local usada na reconstrução: `intent_mvp_v03_en/recipes.sqlite`.
- Histórico de perguntas: `data/train.jsonl`.
- Relatórios anteriores: `tinyslm_v12/normalization_report.json`,
  `tinyslm_v12/full/full_report.json`, `tinyslm_v12/README_V12.md`.
- Catálogo histórico do projeto: `dados/README.md` e
  `docs/FLUXO_COMPLETO.md` no repositório `tinyLLM`.
