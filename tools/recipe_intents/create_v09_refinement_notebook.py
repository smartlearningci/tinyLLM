"""Generate a self-contained Kaggle notebook for intent SFT from epoch_3."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


DEST = Path(__file__).resolve().parents[2] / "notebooks" / "TinySLM_C2_v09_refinamento_intencoes.ipynb"
cells = []


def md(source: str) -> None:
    cells.append({"cell_type": "markdown", "metadata": {}, "source": dedent(source).strip() + "\n"})


def py(source: str) -> None:
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                  "outputs": [], "source": dedent(source).strip() + "\n"})


md("""
    # TinySLM C2 v09 — refinamento para classificar intenções

    Este notebook **continua os pesos do TinySLM `epoch_3`**, sem recomeçar o
    treino inicial, para classificar a intenção de uma pergunta **sem a receita**.

    ### Preparação no Kaggle — três Inputs

    1. Modelo: dataset `epoca3`, contendo `epoch_3/model.safetensors`,
       `config.json`, `tokenizer.json` e `tokenizer_config.json`.
    2. Dataset privado criado a partir do ZIP **`TinySLM_C2_intents_sft_v01.zip`**.
       O notebook aceita tanto o ZIP como os ficheiros extraídos.
    3. Dataset **`TinySLM Culinary Conversations v04`** (ficheiros `train.jsonl`,
       `validation.jsonl`, `dataset_report.json`) para prevenir esquecimento.

    Ativar **GPU T4** (ou equivalente) e escolher **Save Version → Save & Run All**.

    **Importante:** os rótulos do professor são *teacher_unverified*; a precisão
    calculada face a eles mede concordância com o professor, **não** precisão
    certificada por revisão humana. Os exemplos fora do domínio adicionados
    são curados pelo assistente, não verificados por avaliadores independentes.
""")

md("""## 1. Configuração e dispositivo

    Duas épocas experimentais, taxa de aprendizagem conservadora e checkpoints
    após cada época. O tokenizer mantém os mesmos 8.005 tokens do modelo base.
""")

py("""
    import collections, hashlib, json, math, random, shutil, time, zipfile
    from pathlib import Path
    import torch
    from torch.optim import AdamW
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer, LlamaForCausalLM

    SEED = 42
    MAX_LEN = 512
    EPOCHS = 2
    LR = 1e-5
    MICRO_BATCH = 4
    GRAD_ACCUM = 4
    REHEARSAL_PER_CAP = 250
    BASELINE_PROBES = 80
    OUT = Path('/kaggle/working/tinyslm_c2_v09_intents')
    OUT.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    torch.manual_seed(SEED)
    assert torch.cuda.is_available(), 'Ativa uma GPU no painel do Kaggle.'
    torch.cuda.manual_seed_all(SEED)
    device = torch.device('cuda')
    AMP_DTYPE = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    scaler = torch.amp.GradScaler('cuda', enabled=AMP_DTYPE == torch.float16)
    print('GPU:', torch.cuda.get_device_name(0), '| AMP:', AMP_DTYPE)
""")

md("""## 2. Localizar e validar os três inputs

    O notebook procura automaticamente o `epoch_3` e os datasets. Se faltar
    algum, mostra exatamente qual input é necessário adicionar ao Kaggle.
""")

py("""
    INPUT = Path('/kaggle/input')
    assert INPUT.exists(), 'Executar no Kaggle.'

    def exactly_one(found, name):
        found = list(found)
        assert len(found) == 1, f'{name}: encontrado(s) {len(found)}: {found[:8]}'
        return found[0]

    model_folders = sorted({p.parent for p in INPUT.rglob('model.safetensors') if p.parent.name == 'epoch_3'})
    BASE = exactly_one(model_folders, 'Checkpoint epoch_3')
    required = ('model.safetensors','config.json','tokenizer.json','tokenizer_config.json')
    assert all((BASE / x).is_file() for x in required), 'O checkpoint epoch_3 está incompleto.'

    extracted = [p.parent for p in INPUT.rglob('sft_report.json') if (p.parent / 'train.jsonl').is_file()]
    zips = list(INPUT.rglob('TinySLM_C2_intents_sft_v01.zip'))
    assert len(extracted) + len(zips) == 1, 'Adicionar o dataset Kaggle com TinySLM_C2_intents_sft_v01.zip.'
    if extracted:
        SFT = extracted[0]
    else:
        SFT = OUT / 'dataset'
        SFT.mkdir(exist_ok=True)
        with zipfile.ZipFile(zips[0]) as archive:
            assert archive.testzip() is None, 'ZIP de intenções danificado.'
            for name in ('train.jsonl','validation.jsonl','test.jsonl','sft_report.json'):
                (SFT / name).write_bytes(archive.read(name))

    report = json.loads((SFT / 'sft_report.json').read_text(encoding='utf-8'))
    for part in ('train','validation','test'):
        file = SFT / f'{part}.jsonl'
        assert hashlib.sha256(file.read_bytes()).hexdigest() == report[f'{part}_sha256'], f'SHA-256 inválido em {part}'
    assert report['excluded_taxonomy_warnings'] == 200, 'Versão inesperada da auditoria.'

    originals = [p.parent for p in INPUT.rglob('dataset_report.json')
                 if (p.parent / 'train.jsonl').is_file() and (p.parent / 'validation.jsonl').is_file()]
    ORIGINAL = exactly_one(originals, 'Dataset v04 com receitas para rehearsal')
    print('Checkpoint:', BASE)
    print('Intenções:', SFT, '| splits:', report['splits'])
    print('Receitas anteriores:', ORIGINAL)
""")

md("""## 3. Carregar o mesmo TinySLM `epoch_3`

    O refinamento usa **os pesos anteriores**, não inicializa um novo modelo.
    Não altera o tokenizer e não aumenta o número de parâmetros.
""")

py("""
    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    assert len(tok) == 8005, f'Tokenizer inesperado: {len(tok)}'
    assert tok.convert_tokens_to_ids('<|user|>') == 8000
    assert tok.convert_tokens_to_ids('<|assistant|>') == 8001
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = LlamaForCausalLM.from_pretrained(BASE, local_files_only=True, dtype=torch.float32)
    assert model.get_input_embeddings().weight.shape[0] == len(tok)
    model.config.pad_token_id = tok.pad_token_id
    model.to(device)
    print('Parâmetros:', sum(p.numel() for p in model.parameters()))
""")

md("""## 4. Construir exemplos de classificação e revisão de receitas

    A **classificação só recebe a pergunta**. A resposta esperada é um objeto
    JSON com `intent` e `operation`; a *loss* incide apenas na resposta.
    Uma amostra de conversas v04 com contexto de receita é misturada ao treino
    para reduzir o esquecimento das capacidades anteriores.
""")

py("""
    def read_jsonl(file):
        with Path(file).open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)

    intent_train = list(read_jsonl(SFT / 'train.jsonl'))
    intent_val = list(read_jsonl(SFT / 'validation.jsonl'))
    intent_test = list(read_jsonl(SFT / 'test.jsonl'))
    assert len(intent_train) == report['splits']['train']
    assert len(intent_val) == report['splits']['validation']
    assert len(intent_test) == report['splits']['test']
    train_recipes = {r['recipe_id'] for r in intent_train if r.get('recipe_id')}
    heldout_recipes = {r['recipe_id'] for r in intent_val + intent_test if r.get('recipe_id')}
    assert train_recipes.isdisjoint(heldout_recipes), 'Receitas presentes em splits diferentes!'

    SYSTEM_INTENT = (
      'Classify the intention of the culinary user question. No recipe is supplied. '
      'Do not answer the question. Reply ONLY with compact JSON: '
      '{"intent":"...","operation":"..."}. '
      'Allowed pairs: ingredients/list, ingredients/check, quantity/get, '
      'steps/next, steps/explain, steps/rewrite, constraints/check, '
      'constraints/substitute, unknown/unknown. '
      'Use unknown/unknown for off-topic or inseparable multiple intentions.'
    )
    SYSTEM_RECIPE = ('Answer in English using the supplied recipe. Follow the user request. '
                     'If the recipe does not establish an answer, state the missing information.')
    enc = lambda s: tok.encode(s, add_special_tokens=False)

    def intent_prefix(question):
        return [tok.bos_token_id] + enc('<|system|>\\n' + SYSTEM_INTENT +
                                        '\\n<|user|>\\n' + question + '\\n<|assistant|>\\n')

    def pack(prompt_ids, answer):
        target = enc(answer) + [tok.eos_token_id]
        if len(prompt_ids) + len(target) > MAX_LEN:
            return None
        return {'input_ids': prompt_ids + target, 'labels': [-100] * len(prompt_ids) + target}

    def intent_examples(rows):
        examples = []
        for row in rows:
            answer = json.dumps({'intent': row['intent'], 'operation': row['operation']},
                                ensure_ascii=False, separators=(',', ':'))
            prepared = pack(intent_prefix(row['question']), answer)
            if prepared is not None:
                examples.append(prepared)
        return examples

    def recipe_examples(rows):
        examples = []
        for row in rows:
            if not row.get('context') or not row.get('conversation'):
                continue
            context = '\\n\\n'.join(c['text'] for c in row['context']['chunks'])
            for i, msg in enumerate(row['conversation']):
                if msg['role'] != 'assistant':
                    continue
                prompt = [tok.bos_token_id] + enc('<|system|>\\n' + SYSTEM_RECIPE + '\\n')
                for j, previous in enumerate(row['conversation'][:i]):
                    content = previous['content']
                    if j == 0:
                        content = 'Recipe context:\\n' + context + '\\n\\nQuestion:\\n' + content
                    prompt.extend(enc('<|' + previous['role'] + '|>\\n' + content))
                    if previous['role'] == 'assistant':
                        prompt.append(tok.eos_token_id)
                    prompt.extend(enc('\\n'))
                prompt.extend(enc('<|assistant|>\\n'))
                prepared = pack(prompt, msg['content'])
                if prepared is not None:
                    examples.append(prepared)
        return examples

    rng = random.Random(SEED)
    reservoirs = {cap: [] for cap in ('C1','C2','C3','C4','C5','C6','C7')}
    seen = collections.Counter()
    for row in read_jsonl(ORIGINAL / 'train.jsonl'):
        cap = row.get('capability')
        # Do not reintroduce held-out recipe groups through rehearsal.
        if cap not in reservoirs or row.get('recipe_id') in heldout_recipes:
            continue
        seen[cap] += 1
        bucket = reservoirs[cap]
        if len(bucket) < REHEARSAL_PER_CAP:
            bucket.append(row)
        else:
            index = rng.randrange(seen[cap])
            if index < REHEARSAL_PER_CAP:
                bucket[index] = row
    old_train = [row for bucket in reservoirs.values() for row in bucket]
    old_val = list(read_jsonl(ORIGINAL / 'validation.jsonl'))
    old_val = rng.sample(old_val, min(120, len(old_val)))
    recipe_val_recipes = {row['recipe_id'] for row in old_val}
    assert {r['recipe_id'] for r in old_train}.isdisjoint(recipe_val_recipes), 'Fuga no dataset v04!'

    train_examples = intent_examples(intent_train) + recipe_examples(old_train)
    val_examples = intent_examples(intent_val)
    recipe_val_examples = recipe_examples(old_val)
    print('Treino intenções:', len(intent_examples(intent_train)), '| total com receitas:', len(train_examples))
    print('Validação intenções:', len(val_examples), '| validação antiga receitas:', len(recipe_val_examples))
    assert len(val_examples) > 500 and len(train_examples) > 15000

    def collate(group):
        width = max(len(r['input_ids']) for r in group)
        ids = torch.full((len(group), width), tok.pad_token_id, dtype=torch.long)
        labels = torch.full_like(ids, -100)
        mask = torch.zeros_like(ids)
        for i, row in enumerate(group):
            n = len(row['input_ids'])
            ids[i, :n] = torch.tensor(row['input_ids'])
            labels[i, :n] = torch.tensor(row['labels'])
            mask[i, :n] = 1
        return {'input_ids': ids, 'labels': labels, 'attention_mask': mask}

    train_loader = DataLoader(train_examples, batch_size=MICRO_BATCH, shuffle=True,
                              generator=torch.Generator().manual_seed(SEED), collate_fn=collate)
    val_loader = DataLoader(val_examples, batch_size=MICRO_BATCH, collate_fn=collate)
    recipe_val_loader = DataLoader(recipe_val_examples, batch_size=MICRO_BATCH, collate_fn=collate)
""")

md("""## 5. Avaliar antes do refinamento

    Guardamos a perda do modelo base nas intenções e nas receitas anteriores.
    As métricas de classificação são comparadas com rótulos do professor.
""")

py("""
    @torch.no_grad()
    def evaluate_loss(loader):
        model.eval()
        nll = 0.0
        tokens = 0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            count = int((batch['labels'][:, 1:] != -100).sum())
            if count == 0:
                continue
            with torch.autocast('cuda', dtype=AMP_DTYPE):
                loss = model(**batch, use_cache=False).loss
            nll += float(loss.detach()) * count
            tokens += count
        return round(nll / max(tokens, 1), 5)

    @torch.no_grad()
    def predict(question):
        model.eval()
        prompt = torch.tensor([intent_prefix(question)], dtype=torch.long, device=device)
        output = model.generate(prompt, max_new_tokens=48, do_sample=False,
                                pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)
        raw = tok.decode(output[0, prompt.shape[1]:], skip_special_tokens=True).strip()
        try:
            beginning, ending = raw.index('{'), raw.index('}')
            answer = json.loads(raw[beginning:ending + 1])
            return answer.get('intent'), answer.get('operation'), raw
        except (ValueError, AttributeError):
            return None, None, raw

    def evaluate_intents(rows, limit=BASELINE_PROBES):
        chosen = rows[:limit]
        correct = 0
        predictions = []
        for row in chosen:
            intent, operation, raw = predict(row['question'])
            correct += (intent, operation) == (row['intent'], row['operation'])
            predictions.append({'question': row['question'], 'expected': [row['intent'], row['operation']],
                                'predicted': [intent, operation], 'raw': raw[:200]})
        return {'n': len(chosen), 'exact_match': round(correct / max(len(chosen), 1), 4)}, predictions

    before_score, before_predictions = evaluate_intents(intent_val)
    history = [{'stage': 'epoch_3_before_intent_sft',
                'intent_validation_loss': evaluate_loss(val_loader),
                'recipe_validation_loss': evaluate_loss(recipe_val_loader),
                'teacher_validation_agreement': before_score}]
    (OUT / 'baseline_predictions.json').write_text(json.dumps(before_predictions, ensure_ascii=False, indent=2))
    print(history[0])
""")

md("""## 6. Refinar durante duas épocas e guardar os checkpoints

    O otimizador é reiniciado porque o `epoch_3` contém pesos, não o estado
    anterior do AdamW. Os checkpoints são guardados em `/kaggle/working`.
    A cada época medimos também a perda nas respostas às receitas anteriores.
""")

py("""
    optimizer = AdamW(model.parameters(), lr=LR, betas=(0.9, 0.95), weight_decay=0.1)
    total_updates = math.ceil(len(train_loader) / GRAD_ACCUM) * EPOCHS
    warmup = max(1, round(0.05 * total_updates))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda step: min(1.0, (step + 1) / warmup) *
        max(0.1, (total_updates - step) / max(total_updates - warmup, 1))
        if step > warmup else (step + 1) / warmup)
    best_loss = float('inf')
    best_name = None

    for epoch in range(1, EPOCHS + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        started = time.monotonic()
        total_loss = 0.0
        for batch_no, batch in enumerate(train_loader, 1):
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast('cuda', dtype=AMP_DTYPE):
                loss = model(**batch, use_cache=False).loss
            if not torch.isfinite(loss):
                raise RuntimeError('Loss não finita; interromper refinamento.')
            scaler.scale(loss / GRAD_ACCUM).backward()
            total_loss += float(loss.detach())
            if batch_no % GRAD_ACCUM == 0 or batch_no == len(train_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            if batch_no % 100 == 0 or batch_no == len(train_loader):
                elapsed = (time.monotonic() - started) / 60
                remaining = elapsed * (len(train_loader) - batch_no) / batch_no
                print(f'Época {epoch}: {batch_no}/{len(train_loader)} | '
                      f'loss {total_loss / batch_no:.4f} | ETA {remaining:.1f} min', flush=True)

        match, predictions = evaluate_intents(intent_val)
        metrics = {'stage': f'epoch_intents_{epoch}', 'epoch': epoch,
                   'train_loss': round(total_loss / len(train_loader), 5),
                   'intent_validation_loss': evaluate_loss(val_loader),
                   'recipe_validation_loss': evaluate_loss(recipe_val_loader),
                   'teacher_validation_agreement': match,
                   'minutes': round((time.monotonic() - started) / 60, 2)}
        history.append(metrics)
        checkpoint = OUT / f'epoch_intents_{epoch}'
        model.save_pretrained(checkpoint, safe_serialization=True)
        tok.save_pretrained(checkpoint)
        (OUT / f'predictions_epoch_{epoch}.json').write_text(json.dumps(predictions, ensure_ascii=False, indent=2))
        if metrics['intent_validation_loss'] < best_loss:
            best_loss = metrics['intent_validation_loss']
            best_name = checkpoint.name
        (OUT / 'metrics.json').write_text(json.dumps(history, indent=2))
        (OUT / 'best_checkpoint.json').write_text(json.dumps({'checkpoint': best_name, 'val_loss': best_loss}, indent=2))
        print('Métricas:', metrics, flush=True)
""")

md("""## 7. Teste final independente do treino e exportação

    O `test.jsonl` não foi usado para escolher o checkpoint. Contém referências
    do professor e alguns exemplos fora do domínio curados pelo assistente;
    **não** é um benchmark humano certificado. O ZIP final inclui os pesos
    do melhor checkpoint, tokenizer e relatórios, sem publicar nada automaticamente.
""")

py("""
    # Evaluate the BEST validation checkpoint, even if it was epoch 1.
    if best_name != f'epoch_intents_{EPOCHS}':
        model = LlamaForCausalLM.from_pretrained(OUT / best_name, local_files_only=True,
                                                  dtype=torch.float32).to(device)
        model.config.pad_token_id = tok.pad_token_id
    result = []
    by_source = collections.defaultdict(lambda: {'correct': 0, 'total': 0})
    for row in intent_test:
        pred_intent, pred_op, raw = predict(row['question'])
        success = (pred_intent, pred_op) == (row['intent'], row['operation'])
        group = 'assistant_curated_offdomain' if row['source'] == 'assistant_curated_offdomain' else 'teacher_unverified'
        by_source[group]['correct'] += bool(success)
        by_source[group]['total'] += 1
        result.append({'id': row['id'], 'expected': [row['intent'], row['operation']],
                       'predicted': [pred_intent, pred_op], 'correct': bool(success),
                       'source': group, 'raw': raw[:160]})
    summary = {group: {'n': data['total'], 'agreement': round(data['correct'] / data['total'], 4)}
               for group, data in by_source.items()}
    (OUT / 'test_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (OUT / 'test_summary.json').write_text(json.dumps(summary, indent=2))
    print('Teste final:', summary)
    print('Histórico:', history)

    archive_path = Path('/kaggle/working/TinySLM_C2_v09_refinamento_resultados.zip')
    best = OUT / best_name
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for folder in (best,):
            for item in folder.rglob('*'):
                if item.is_file():
                    archive.write(item, item.relative_to(OUT))
        for name in ('metrics.json','best_checkpoint.json','test_results.json','test_summary.json',
                     'baseline_predictions.json'):
            archive.write(OUT / name, name)
    print('Exportado:', archive_path, '| MB:', round(archive_path.stat().st_size / 1e6, 1))
    print('Ver Save Version → Output para descarregar o resultado.')
""")


def main() -> None:
    payload = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "cells": cells,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("Notebook criado:", DEST)


if __name__ == "__main__":
    main()
