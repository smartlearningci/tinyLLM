#!/usr/bin/env python3
"""Histórias PT-BR -> PT-PT: recolha, adaptação LLM, pré-auditoria,
revisão humana por lotes e publicação apenas de lotes aprovados.

NUNCA declara uma história PT-PT sem adaptação + controlos + aprovação.
Deps para 'recolher': datasets; para adaptação: API OpenAI-compatible (local ou externa).
Restantes operações apenas biblioteca padrão Python.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import json
import os
import re
import sqlite3
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from build_ptpt import ROOT, aceitavel, digest, iter_jsonl_gz, normalizar, escrever

DATASETS = {
    'tinystories': ('DominuZ/TinyStories-pt-BR', 'tinystories_ptbr'),
    'historinhas': ('Boakpe/historinhas', 'historinhas_ptbr'),
}
PROMPT_V = 'ptpt-stories-adapt-v1'
PROMPT = '''És revisor literário de Portugal e especialista em português europeu.
Reescreve a história infantil fornecida em português de Portugal (PT-PT), com
vocabulário, sintaxe, colocações pronominais, diálogos, pontuação e ortografia
naturais em Portugal. Mantém o enredo, personagens, acontecimentos, extensão
aproximada, tom simples e significado. Corrige brasileirismos e formulações
estranhas, mas não inventes acontecimentos nem comentários. Não resumas.
Devolve APENAS o texto completo da história reescrita, sem título adicional,
sem aspas de enquadramento, sem markdown, sem notas e sem raciocínio.'''
# São sinais para revisão, não um classificador linguístico infalível.
BR_SINAIS = {
    'ônibus': r'\bônibus\b', 'celular': r'\bcelular\b', 'sorvete': r'\bsorvete\b',
    'trem': r'\btrem\b', 'ônibus escolar': r'\bônibus escolar\b',
    'suco': r'\bsuco\b', 'geladeira': r'\bgeladeira\b', 'banheiro': r'\bbanheiro\b',
    'cachorro': r'\bcachorro\b', 'vovó/vovô': r'\bvo(?:vó|vô|vós|vôs)\b',
    'mamãe/papai': r'\b(?:mamãe|papai)\b', 'garotinho/garotinha': r'\bgarotinh[oa]s?\b',
    'fazendeiro': r'\bfazendeir[oa]s?\b', 'grama': r'\bgrama\b',
    'a gente': r'\ba gente\b', 'calçada': r'\bcalçada\b',
    'me viu': r'\bme (?:viu|disse|contou|deu|levou|chamou)\b',
    'viu ela': r'\bviu ela\b', 'se viu': r'\bse viu\b',
    'estava fazendo': r'\bestav[ao] (?:fazendo|andando|comendo|brincando)\b',
    'ficou olhando': r'\bficou olhando\b',
}
BR_PATTERNS = {k: re.compile(v, flags=re.I) for k, v in BR_SINAIS.items()}
WORD = re.compile(r'\b[\wÀ-ÿ]+\b', flags=re.U)


def ler_linhas(path: Path):
    if path.suffix == '.gz':
        yield from iter_jsonl_gz(path)
    else:
        with path.open(encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def inserir_arquivo(path: Path, linhas, append=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'at' if append else 'xt'
    with gzip.open(path, mode, encoding='utf-8') as f:
        for row in linhas:
            escrever(f, row)


def extrair_historia(row: dict):
    texto = next((row[k] for k in ('texto', 'text', 'story', 'content')
                  if isinstance(row.get(k), str) and row[k].strip()), '')
    return normalizar(texto)


def candidatos_linhas(rows, dataset: str, max_rows=0):
    n = 0
    for row in rows:
        texto = extrair_historia(row)
        if not aceitavel(texto, min_palavras=50):
            continue
        sha = digest(texto)
        titulo = normalizar(row.get('titulo') or row.get('title') or '')
        yield {'id': dataset + ':' + sha[:24], 'source': dataset,
               'lang_original': 'pt-BR', 'text_original': texto,
               'sha_original': sha, 'titulo_original': titulo,
               'dataset_id': DATASETS[dataset][0],
               'dataset_row_id': str(row.get('id') or '')}
        n += 1
        if max_rows and n >= max_rows:
            break


def recolher(dataset, saida: Path, max_rows: int = 0, rows=None):
    if saida.exists():
        raise FileExistsError(saida)
    if rows is None:
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise RuntimeError('Instala: pip install datasets') from e
        rows = load_dataset(DATASETS[dataset][0], split='train', streaming=True)
    vistos = set()
    r = Counter()
    def it():
        for reg in candidatos_linhas(rows, dataset, max_rows):
            r['lidos_validos'] += 1
            if reg['sha_original'] in vistos:
                r['duplicados'] += 1
                continue
            vistos.add(reg['sha_original'])
            r['recolhidos'] += 1
            yield reg
    inserir_arquivo(saida, it())
    return dict(r)


def sinais_br(texto):
    return [k for k, pat in BR_PATTERNS.items() if pat.search(texto)]


def api_reescrever(texto, url, model, api_key='', timeout=120, retries=3):
    # URL explícita: local por omissão. Não registar chaves ou devolver o token.
    if not url.startswith(('http://127.0.0.1:', 'http://localhost:', 'https://')):
        raise ValueError('Usa HTTPS para endpoints remotos; localhost HTTP é permitido.')
    payload = {'model': model, 'messages': [
        {'role': 'system', 'content': PROMPT},
        {'role': 'user', 'content': texto}], 'temperature': 0.15, 'stream': False}
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                  headers=headers, method='POST')
    err = None
    for attempt in range(max(1, retries)):
        try:
            with urlopen(req, timeout=timeout) as resp:
                js = json.load(resp)
            s = js['choices'][0]['message']['content']
            if isinstance(s, list):
                s = ''.join(v.get('text', '') for v in s if isinstance(v, dict))
            s = normalizar(str(s))
            s = re.sub(r'^```(?:\w+)?\s*|\s*```$', '', s).strip()
            if '<think>' in s or '</think>' in s:
                raise ValueError('A resposta inclui raciocínio interno em vez de texto final.')
            return s
        except (HTTPError, URLError, OSError, ValueError, KeyError, IndexError) as e:
            err = e
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError('Falha no endpoint de adaptação: ' + str(err)[:200])


def adaptar(raw: Path, saida: Path, endpoint: str, model: str, *, limit=0,
            lote_tamanho=1000, sleep=0, api_key='', client=None):
    if not raw.is_file():
        raise FileNotFoundError(raw)
    saida.parent.mkdir(parents=True, exist_ok=True)
    # Retomar: entradas já convertidas mantêm-se, incluindo casos com falha.
    concluidos = {x['id'] for x in ler_linhas(saida)} if saida.exists() else set()
    feitos = 0
    falhas = 0
    func = client or (lambda s: api_reescrever(s, endpoint, model, api_key))
    with gzip.open(saida, 'at' if saida.exists() else 'xt', encoding='utf-8') as out:
        for n, reg in enumerate(ler_linhas(raw)):
            if reg['id'] in concluidos:
                continue
            if limit and feitos >= limit:
                break
            batch_id = reg['source'] + ':' + str(n // lote_tamanho).zfill(6)
            try:
                converted = func(reg['text_original'])
                status = 'pending_audit'
                erro = ''
            except Exception as e:
                converted, status, erro = '', 'error', str(e)[:250]
                falhas += 1
            result = dict(reg, text_ptpt=normalizar(converted),
                          sha_ptpt=digest(normalizar(converted)) if converted else '',
                          batch_id=batch_id, model=model,
                          prompt_version=PROMPT_V, status=status, error=erro)
            escrever(out, result)
            out.flush()
            feitos += 1
            if sleep:
                time.sleep(sleep)
    return {'processadas_agora': feitos, 'falhas': falhas,
            'anteriormente_concluidas': len(concluidos), 'output': str(saida)}


def auditar_registro(reg, *, min_words=70, max_words=800):
    reasons = []
    a, b = reg.get('text_original', ''), reg.get('text_ptpt', '')
    if reg.get('status') != 'pending_audit':
        reasons.append('sem_adaptacao_valida')
    n = len(WORD.findall(b))
    if not (min_words <= n <= max_words):
        reasons.append('comprimento_fora_limites')
    if not aceitavel(b, min_palavras=min_words, max_chars=18000):
        reasons.append('texto_ilegivel_ou_curto')
    ratio = len(b) / max(1, len(a))
    if not (0.6 <= ratio <= 1.55):
        reasons.append('alteracao_de_extensao_excessiva')
    if digest(normalizar(a)) == digest(normalizar(b)):
        reasons.append('texto_nao_adaptado')
    if any(v in b.lower() for v in ('<think>', '<html', '```', 'como modelo de linguagem')):
        reasons.append('artefacto_de_modelo')
    br = sinais_br(b)
    if br:
        reasons.append('sinais_ptbr:' + ','.join(br))
    return {'auto_ok': not reasons, 'issues': reasons, 'words_ptpt': n,
            'ratio_chars': round(ratio, 3)}


def auditar(adaptados: Path, saida: Path):
    if saida.exists():
        raise FileExistsError(saida)
    c = Counter()
    def it():
        for reg in ler_linhas(adaptados):
            r = auditar_registro(reg)
            c['vistos'] += 1
            c['pre_aprovados' if r['auto_ok'] else 'rejeitados_automaticamente'] += 1
            for issue in r['issues']:
                c['erro:' + issue.split(':')[0]] += 1
            yield {**reg, **r}
    inserir_arquivo(saida, it())
    return dict(c)


def _selecionar_amostra(auditados: Path, por_lote: int):
    if por_lote < 1:
        raise ValueError('por_lote deve ser pelo menos 1')
    # Reservatório determinístico por lote; dá preferência a exemplos com alerta.
    groups = defaultdict(list)
    totals = Counter()
    for r in ler_linhas(auditados):
        key = r['batch_id']
        totals[key] += 1
        score = int(hashlib.sha256((key + r['id']).encode()).hexdigest()[:16], 16)
        # Para assegurar observação dos dois tipos de saída, amostragem de todos
        heap = groups[key]
        entry = (-score, r['id'], r)
        if len(heap) < por_lote:
            heapq.heappush(heap, entry)
        elif entry[0] > heap[0][0]:
            heapq.heapreplace(heap, entry)
    return groups, totals


def gerar_amostra(auditados: Path, csv_path: Path, por_lote=20):
    """Amostra estável por lote; requer revisão explícita."""
    if csv_path.exists():
        raise FileExistsError(csv_path)
    groups, totals = _selecionar_amostra(auditados, por_lote)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['batch_id', 'id', 'sha_ptpt',
                           'auto_ok', 'issues', 'original_ptbr', 'adaptado_ptpt',
                           'aprovada', 'observacoes'])
        w.writeheader()
        for batch in sorted(groups):
            for _, _, reg in sorted(groups[batch], key=lambda e: e[1]):
                w.writerow({'batch_id': batch, 'id': reg['id'], 'sha_ptpt': reg['sha_ptpt'],
                            'auto_ok': reg['auto_ok'], 'issues': '|'.join(reg['issues']),
                            'original_ptbr': reg['text_original'], 'adaptado_ptpt': reg['text_ptpt'],
                            'aprovada': '', 'observacoes': ''})
    return {'lotes': len(groups), 'amostras': sum(map(len,groups.values())),
            'registos_por_lote': dict(totals)}


def validar_revisao(csv_path: Path):
    outcomes = defaultdict(lambda: {'sim': 0, 'nao': 0, 'pendente': 0, 'hashes': {}})
    with csv_path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            batch, id = row['batch_id'], row['id']
            v = row['aprovada'].strip().lower()
            status = 'sim' if v in ('sim','s','yes','y') else ('nao' if v in ('não','nao','n','no') else 'pendente')
            if id in outcomes[batch]['hashes']:
                raise ValueError('Revisão com ID repetido: ' + id)
            outcomes[batch]['hashes'][id] = row['sha_ptpt']
            outcomes[batch][status] += 1
    return outcomes


def fingerprint(texto: str):
    """SimHash 64-bit sobre trigramas, para detetar quase duplicados."""
    w = [x.casefold() for x in WORD.findall(normalizar(texto))]
    if len(w) < 5:
        return 0
    scores = [0] * 64
    for i in range(len(w) - 2):
        gram = (' '.join(w[i:i+3])).encode('utf-8')
        val = int.from_bytes(hashlib.blake2b(gram, digest_size=8).digest(), 'big')
        for bit in range(64):
            scores[bit] += 1 if (val >> bit) & 1 else -1
    return sum((1 << b) for b in range(64) if scores[b] >= 0)


class NearDuplicates:
    """Quase duplicados por MinHash de trigramas + Jaccard exato.

    Os oito mínimos dão candidatos, que só se rejeitam se a sobreposição real
    dos trigramas passar o limiar. Não usa comparações quadráticas.
    """
    def __init__(self, path=':memory:', threshold=0.82):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE docs (docid INTEGER PRIMARY KEY, grams BLOB)')
        self.db.execute('CREATE TABLE keys (gramhash INTEGER, docid INTEGER)')
        self.db.execute('CREATE INDEX ix_minhash ON keys(gramhash)')
        self.threshold = threshold
        self.checks = 0

    @staticmethod
    def _grams(text):
        words = [w.casefold() for w in WORD.findall(normalizar(text))]
        return {int.from_bytes(hashlib.blake2s(' '.join(words[i:i+3]).encode('utf-8'),
                     digest_size=4).digest(), 'big')
                for i in range(max(0, len(words)-2))}

    def add(self, txt):
        grams = self._grams(txt)
        if not grams:
            return False
        anchors = sorted(grams)[:8]
        docs = set()
        for h in anchors:
            for (docid,) in self.db.execute('SELECT docid FROM keys WHERE gramhash=?', (h,)):
                docs.add(docid)
        self.checks += 1
        import array
        for docid in docs:
            (blob,) = self.db.execute('SELECT grams FROM docs WHERE docid=?', (docid,)).fetchone()
            arr = array.array('I'); arr.frombytes(zlib.decompress(blob))
            if len(grams.intersection(arr)) / len(grams.union(arr)) >= self.threshold:
                return False
        arr = array.array('I', sorted(grams))
        if __import__('sys').byteorder != 'little':
            arr.byteswap()
        blob = zlib.compress(arr.tobytes(), 3)
        cur = self.db.execute('INSERT INTO docs(grams) VALUES (?)', (blob,))
        self.db.executemany('INSERT INTO keys VALUES (?,?)', ((h, cur.lastrowid) for h in anchors))
        return True

    def close(self):
        self.db.commit()
        self.db.close()


def publicar(auditados: Path, revisao: Path, output_dir: Path, *, val_permille=5, por_lote=20):
    """Só publica lotes cuja amostra foi integralmente revista e sem reprovações.

    Ficheiros imutáveis; divisão estável por grupo de história após deduplicação.
    """
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('A versão já existe: ' + str(output_dir))
    if not 1 <= val_permille <= 50:
        raise ValueError('val_permille fora de 1..50')
    reviewed = validar_revisao(revisao)
    expected, _ = _selecionar_amostra(auditados, por_lote)
    for batch, heap in expected.items():
        exp = {r['id']: r['sha_ptpt'] for _, _, r in heap}
        got = reviewed.get(batch)
        if got and got['hashes'] != exp:
            raise ValueError('Ficheiro de revisão incompleto/adulterado no lote: ' + batch)
    if set(reviewed).difference(expected):
        raise ValueError('Revisão contém lotes que não pertencem ao dataset.')
    output_dir.mkdir(parents=True, exist_ok=True)
    train = output_dir / 'historias_train.jsonl.gz'
    val = output_dir / 'historias_validation.jsonl.gz'
    stats = Counter()
    near = NearDuplicates(str(output_dir / '_near.sqlite'))
    hashes = set()
    # Verificar se a assinatura dos registos auditados coincide com as amostras.
    with gzip.open(train, 'xt', encoding='utf-8') as tr, gzip.open(val, 'xt', encoding='utf-8') as va:
        for r in ler_linhas(auditados):
            stats['vistos'] += 1
            dec = reviewed.get(r['batch_id'])
            if not dec or dec['pendente'] or dec['nao'] or dec['sim'] == 0:
                stats['lote_sem_aprovacao'] += 1
                continue
            if r['id'] in dec['hashes'] and dec['hashes'][r['id']] != r['sha_ptpt']:
                raise ValueError('Conteúdo alterado depois de revisão: ' + r['id'])
            if not r.get('auto_ok'):
                stats['falhou_auditoria_automatica'] += 1
                continue
            txt = r['text_ptpt']
            h = digest(txt)
            if h in hashes:
                stats['duplicado_exato'] += 1
                continue
            if not near.add(txt):
                stats['quase_duplicado'] += 1
                continue
            hashes.add(h)
            # Separação por família do original, e não por posição no ficheiro.
            origin = r['sha_original']
            group = 'story:' + origin
            seed = int(hashlib.sha256(('ptpt-v1|' + group).encode()).hexdigest()[:8], 16)
            split = 'validation' if seed % 1000 < val_permille else 'train'
            doc = {'id': r['id'], 'group': group, 'source': r['source'] + '_adaptado_ptpt',
                   'lang': 'pt-PT', 'text': txt, 'model_adaptacao': r['model'],
                   'sha_original': origin, 'sha_ptpt': h, 'prompt_version': r['prompt_version']}
            escrever(va if split == 'validation' else tr, doc)
            stats[split] += 1
    near.close()
    (output_dir / '_near.sqlite').unlink(missing_ok=True)
    for key in ('train', 'validation', 'lote_sem_aprovacao'):
        stats[key] += 0
    report = dict(stats, stage='historias_aprovadas', manual_review=str(revisao),
                  automated_audit=str(auditados),
                  note='A aprovação por amostragem não demonstra conformidade PT-PT perfeita.')
    (output_dir / 'historias_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def juntar_aprovadas(entradas: list[Path], out_dir: Path, *, meta_historias=100000, val_permille=5):
    """Une as fontes adaptadas e aprovadas, deduplicando TAMBÉM entre fontes.

    Os diretórios indicados precisam de `historias_report.json` e os dois
    splits. Não aceita dados brutos nem adaptações não auditadas.
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError('Versão já existente: ' + str(out_dir))
    if not 1 <= val_permille <= 50:
        raise ValueError('val_permille deve estar entre 1 e 50')
    all_files = []
    for pasta in entradas:
        if not (pasta/'historias_report.json').is_file():
            raise ValueError('Histórias sem relatório de aprovação humana: '+str(pasta))
        for split in ('train','validation'):
            f = pasta / f'historias_{split}.jsonl.gz'
            if not f.is_file():
                raise FileNotFoundError(f)
            all_files.append(f)
    if not all_files:
        raise ValueError('Nenhuma história aprovada foi fornecida')
    out_dir.mkdir(parents=True, exist_ok=True)
    near = NearDuplicates(str(out_dir/'_seen.sqlite'))
    hashes = set()
    result = Counter()
    try:
        with gzip.open(out_dir/'historias_train.jsonl.gz','xt',encoding='utf-8') as tr, \
             gzip.open(out_dir/'historias_validation.jsonl.gz','xt',encoding='utf-8') as va:
            for f in all_files:
                for reg in ler_linhas(f):
                    result['candidatas'] += 1
                    if reg.get('lang') != 'pt-PT' or not reg.get('source','').endswith('_adaptado_ptpt'):
                        raise ValueError('Foi introduzida história não aprovada/sem etiqueta PT-PT')
                    txt = normalizar(reg['text'])
                    h = digest(txt)
                    if h in hashes:
                        result['duplicados_exatos'] += 1
                        continue
                    if not near.add(txt):
                        result['duplicados_aproximados'] += 1
                        continue
                    hashes.add(h)
                    group = str(reg.get('group') or reg.get('sha_original') or h)
                    seed = int(hashlib.sha256(('ptpt-v1|' + group).encode()).hexdigest()[:8],16)
                    split = 'validation' if seed % 1000 < val_permille else 'train'
                    escrever(va if split == 'validation' else tr, dict(reg,group=group,text=txt))
                    result[split] += 1
    finally:
        near.close()
        (out_dir/'_seen.sqlite').unlink(missing_ok=True)
    for key in ('train','validation'):
        result[key] += 0
    total = result['train'] + result['validation']
    report = dict(result, meta_historias=meta_historias, total_aceites=total,
                  meta_atingida=total >= meta_historias,
                  fontes=[str(x) for x in entradas],
                  nota='Lotes já revistos e deduplicados entre fontes; ainda requer controlo linguístico final.')
    (out_dir/'historias_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('recolher')
    s.add_argument('--dataset', choices=sorted(DATASETS), required=True)
    s.add_argument('--out', type=Path, required=True)
    s.add_argument('--max-rows', type=int, default=0)
    s = sub.add_parser('adaptar')
    s.add_argument('--raw', type=Path, required=True)
    s.add_argument('--out', type=Path, required=True)
    s.add_argument('--endpoint', default='http://127.0.0.1:11434/v1/chat/completions')
    s.add_argument('--model', required=True)
    s.add_argument('--api-key-env', default='OPENAI_API_KEY')
    s.add_argument('--limit', type=int, default=0)
    s.add_argument('--lote-tamanho', type=int, default=1000)
    s.add_argument('--sleep', type=float, default=0)
    s = sub.add_parser('auditar')
    s.add_argument('--adaptados', type=Path, required=True)
    s.add_argument('--out', type=Path, required=True)
    s = sub.add_parser('amostrar')
    s.add_argument('--auditados', type=Path, required=True)
    s.add_argument('--csv', type=Path, required=True)
    s.add_argument('--por-lote', type=int, default=20)
    s = sub.add_parser('juntar-aprovadas')
    s.add_argument('--fontes', nargs='+', type=Path, required=True)
    s.add_argument('--out-dir', type=Path, required=True)
    s.add_argument('--meta-historias', type=int, default=100000)
    s.add_argument('--val-permille', type=int, default=5)
    s = sub.add_parser('publicar')
    s.add_argument('--auditados', type=Path, required=True)
    s.add_argument('--revisao', type=Path, required=True)
    s.add_argument('--out-dir', type=Path, required=True)
    s.add_argument('--val-permille', type=int, default=5)
    s.add_argument('--por-lote', type=int, default=20)
    a = p.parse_args(argv)
    if a.cmd == 'recolher':
        result = recolher(a.dataset, a.out, a.max_rows)
    elif a.cmd == 'adaptar':
        result = adaptar(a.raw, a.out, a.endpoint, a.model, limit=a.limit,
                        lote_tamanho=a.lote_tamanho, sleep=a.sleep,
                        api_key=os.environ.get(a.api_key_env, ''))
    elif a.cmd == 'auditar':
        result = auditar(a.adaptados, a.out)
    elif a.cmd == 'amostrar':
        result = gerar_amostra(a.auditados, a.csv, por_lote=a.por_lote)
    elif a.cmd == 'publicar':
        result = publicar(a.auditados, a.revisao, a.out_dir, val_permille=a.val_permille, por_lote=a.por_lote)
    else:
        result = juntar_aprovadas(a.fontes,a.out_dir,meta_historias=a.meta_historias,val_permille=a.val_permille)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()