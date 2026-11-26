# TinySLM-PTPT v1.2 — tarefas, responsável e estado

> **Estado 26/11/2026:** implementação do código e testes locais avançada; **dados integrais, adaptação em massa e treino ainda não executados**. Marcar tarefas como concluídas **só** depois de verificar relatórios reais.

| Nº | Tarefa | Estado | Resultado atual / dependência |
|---:|---|---|---|
| 1 | Fixar três componentes do corpus e exclusão de PT-BR cru | ✅ Código/manifesto | `corpus_v1.json` |
| 2 | CETEMPúblico `.gz` em streaming | ✅ Implementado, testes com exemplo | `build_ptpt.py cetem`; falta ficheiro real no ambiente de treino |
| 3 | Bagaço2 `all`, streaming, filtros PT-PT/educação | ✅ Implementado | `build_ptpt.py bagaco`; falta recolha real |
| 4 | Obter ELTeC-por nível 1 com checksum | ✅ Implementado | `fontes_literarias.py obter-eltec`; falta executar download real |
| 5 | Extrair ELTeC TEI e manter split por obra | ✅ Implementado/testado | XML local; sem quotas automáticas |
| 6 | Extrair ParlaMint-PT XML de sessões | ✅ Implementado/testado | Falta obter ficheiros originais da CLARIN |
| 7 | Extrair Adamastor EPUB na ordem correta | ✅ Implementado/testado | Falta selecionar/obter EPUB elegíveis |
| 8 | Evitar descarte de romances por tamanho | ✅ Corrigido/testado | Blocos até 12k caracteres por obra |
| 9 | FairytaleQA separado e SFT por split | ✅ Implementado/testado | `build_ptpt.py fairytale` + `pipeline_ptpt.py preparar-qa`; falta HF real |
| 10 | Ingerir TinyStories-pt-BR e Boakpe em streaming | ✅ Implementado/testado com esquema simulado | `historias_ptpt.py recolher`; falta testar download HF real |
| 11 | Reescrita PT-BR→PT-PT por API de LLM, com retoma | ✅ Implementado/testado com cliente falso | Requer escolha de modelo/endpoints e medição de custo |
| 12 | Auditoria de brasileirismos e problemas de adaptação | ✅ Implementado/testado | São heurísticas; requer inspeção humana |
| 13 | Amostragem por lote + aprovação humana | ✅ Implementado/testado | Falta revisão humana de resultados reais |
| 14 | Deduplicar histórias quase iguais, cruzar fontes e criar splits | ✅ Implementado/testado | `historias_ptpt.py juntar-aprovadas`; falta executar nos dados reais |
| 15 | Verificar grupos/dedup exata entre splits no corpus geral | ✅ Implementado/testado | `finalizar_dataset.py auditar`; quase duplicados gerais por verificar |
| 16 | Agregar fontes, treinar tokenizer e reequilibrar por quotas em tokens | ✅ Scripts implementados | Falta executar em dados reais para verificar 400 M tokens |
| 17 | Codificar uint16 e inventariar SHA/tokens | ✅ Scripts implementados | Falta execução real e validação em grandes volumes |
| 18 | Controlar estado e impedir release integral incompleta | ✅ Implementado | `pipeline_ptpt.py estado` / `finalizar-geral` |
| 19 | Gerar pacote privado para Kaggle | ✅ Implementado | `finalizar_dataset.py kaggle`; falta artefactos reais |
| 20 | Selecionar modelo de adaptação PT-PT competente | ⏳ Pendente | Experimentar 50 histórias, medir correções e custo/tempo |
| 21 | Recolher 400 M tokens gerais úteis, após filtros | ⏳ Pendente | Recolha, quota real por tokenizer, dedup aproximada e auditoria |
| 22 | Adaptar e aprovar 100 000 histórias PT-PT distintas | ⏳ Pendente | LLM adequado, revisão, execução longa, dedup cruzada |
| 23 | Auditar licenças/atribuição e contaminação train/validation/test | ⏳ Pendente | Especial atenção a CETEMPúblico, fontes web e traduções |
| 24 | Integrar fase de histórias e SFT no notebook do Kaggle | ⏳ Pendente | Treino do modelo em separado do pipeline de dados |
| 25 | Medir comportamento PT-PT do modelo depois do treino | ⏳ Pendente | Testes linguísticos humanos PT-PT, não apenas loss |

## Ordem operacional

1. Obter **CETEMPúblico**, **Bagaço2**, **ELTeC**, **ParlaMint-PT**, **Adamastor** e **FairytaleQA**; cada fonte fica num ficheiro separado.
2. Converter uma amostra de 50 histórias em PT-PT com um LLM validado; corrigir prompt/fornecedor se necessário.
3. Aumentar em lotes e rever CSVs; gerar 100 mil histórias efetivamente aceites, sem misturar PT-BR.
4. Produzir versões imutáveis; verificar contagens por fonte e cruzamento de duplicados.
5. Gerar tokenizer, binários, hash e pacote privado para Kaggle.
6. Treinar de raiz e avaliar, depois especializar nas receitas portuguesas.