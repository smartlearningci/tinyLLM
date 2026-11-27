# Pingo Doce — recolha culinária para TinySLM

Este módulo foi recuperado da versão anteriormente fornecida como ficheiro de conversa, mas que não tinha sido adicionada ao repositório.

## Comandos

Na raiz do `tinyLLM`, sem dependências adicionais:

```bash
# Ver estado da base local (cria tabelas se ainda não existir)
python tools/corpus_culinaria/pingodoce.py

# Recolher uma amostra de até 10 páginas, APENAS se a recolha e uso
# estiverem efetivamente autorizados e conformes com robots.txt/termos
python tools/corpus_culinaria/pingodoce.py --collect --permission-confirmed --limit 10

# Continuar incrementalmente (não repete páginas aceites)
python tools/corpus_culinaria/pingodoce.py --collect --permission-confirmed
```

A opção `--permission-confirmed` **não concede nem demonstra** autorização: apenas regista que o utilizador confirmou por sua responsabilidade que dispõe das permissões necessárias. O programa consulta e respeita `robots.txt`; não contorna bloqueios HTTP 403, 429 ou 503. Se ocorrer algum destes códigos, **não tentar ultrapassar os limites**; confirmar antes a permissão de recolha. O script aguarda pelo menos 2 segundos entre pedidos e exige acesso ao domínio `www.pingodoce.pt`.

A descoberta usa `sitemap.xml` e procura sitemaps de receitas e técnicas (`recipe-sitemap*.xml` e `cooking_techniques-sitemap*.xml`). A extração usa apenas JSON-LD com schema `Recipe` ou `HowTo`. Alterações ao site podem exigir ajustes; não há garantia de que o site permita ou disponibilize a recolha.

## Saídas

- `dados/culinaria/pingodoce.sqlite`: base SQLite com estado das páginas, dados de origem e extração normalizada; permite retomar.
- `dados/culinaria/pingodoce.jsonl`: dados normalizados com `url`, `kind` e `context`. **O `context` é texto natural em português**, para fornecer ao TinySLM; JSONL é apenas formato de armazenamento/transporte, não o texto apresentado ao modelo.

**Atenção:** a extração inicial mantém ingredientes como texto, sem validar todas as unidades/quantidades; técnicas e instruções de alta qualidade, substituições e perguntas/respostas requerem normalização e auditoria posteriores. Não tratar os registos como dataset validado antes dessa fase. A redistribuição, processamento e treino com conteúdo de terceiros dependem de direitos aplicáveis e condições de uso.

## Testes locais sem rede

```bash
python -m unittest discover -s tools/corpus_culinaria -p 'test_*.py' -v
```