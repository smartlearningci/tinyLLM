#!/usr/bin/env python3
"""Recolhe Boakpe/historinhas pela API /rows, sem abrir o JSON de 1,63 GB.

Cada página é guardada atomicamente e a recolha pode ser retomada após erro
ou interrupção. Só cria o .jsonl.gz final depois de ter registos válidos.
Este script utiliza apenas a biblioteca padrão do Python 3.10+.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATASET = 'Boakpe/historinhas'
BASE_URL = 'https://datasets-server.huggingface.co/rows'
PAGE_SIZE = 100


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize('NFC', texto).replace('\ufeff', '').replace('\xa0', ' ')
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(re.sub(r'[ \t\f\v]+', ' ', ln).strip() for ln in texto.split('\n')).strip()


def registo_da_linha(row: dict, row_idx: int):
    texto = row.get('texto')
    if not isinstance(texto, str):
        return None
    texto = normalizar(texto)
    if not (140 <= len(texto) <= 250000):
        return None
    if len(re.findall(r'\w+', texto, re.UNICODE)) < 50:
        return None
    if sum(c.isalpha() for c in texto) / len(texto) <= .45:
        return None
    sha = hashlib.sha256(texto.encode('utf-8')).hexdigest()
    return {
        'id': f'historinhas:{sha[:24]}',
        'source': 'historinhas',
        'lang_original': 'pt-BR',
        'text_original': texto,
        'sha_original': sha,
        'titulo_original': normalizar(row.get('titulo') or ''),
        'dataset_id': DATASET,
        'dataset_row_id': str(row_idx),
    }


def pedir_pagina(offset: int, length: int = PAGE_SIZE, *, timeout: float = 35,
                 retries: int = 4, pausa_429: float = 120):
    """Respeita HTTP 429 e o cabeçalho Retry-After; sem pedidos em rajada."""
    if pausa_429 < 0:
        raise ValueError('pausa_429 não pode ser negativa')
    url = BASE_URL + '?' + urlencode({
        'dataset': DATASET, 'config': 'default', 'split': 'train',
        'offset': offset, 'length': length,
    })
    erro = None
    for n in range(retries):
        try:
            request = Request(url, headers={'User-Agent': 'TinySLM-PTPT/1.1'})
            with urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            if not isinstance(data.get('rows'), list):
                raise ValueError('Resposta /rows sem uma lista rows. Verifica a disponibilidade da API.')
            return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            erro = e
            print(f'Falha na página {offset} (tentativa {n+1}/{retries}): {str(e)[:160]}',
                  file=sys.stderr, flush=True)
            if isinstance(e, HTTPError) and e.code in (400, 401, 403, 404):
                raise RuntimeError(f'HTTP {e.code} ao pedir a página {offset}; verificar permissão/configuração, sem repetir pedidos.') from e
            if n + 1 >= retries:
                break
            espera = min(2 ** n, 8)
            if isinstance(e, HTTPError) and e.code == 429:
                espera = max(pausa_429 * (n + 1), espera)
                retry_after = e.headers.get('Retry-After') if e.headers else None
                if retry_after:
                    try:
                        espera = max(espera, float(retry_after))
                    except (ValueError, TypeError):
                        from email.utils import parsedate_to_datetime
                        from datetime import datetime, timezone
                        try:
                            quando = parsedate_to_datetime(retry_after)
                            if quando.tzinfo is None:
                                quando = quando.replace(tzinfo=timezone.utc)
                            espera = max(espera, (quando - datetime.now(timezone.utc)).total_seconds())
                        except (TypeError, ValueError, OverflowError):
                            pass
                print(f'Limite 429: aguardar {espera:.0f} segundos antes de repetir.',
                      file=sys.stderr, flush=True)
            time.sleep(espera)
    raise RuntimeError(f'Não foi possível ler a página {offset}; os blocos anteriores ficaram guardados. Último erro: {erro}')


def escrever_pagina(pasta: Path, offset: int, registos: list[dict]):
    pasta.mkdir(parents=True, exist_ok=True)
    path = pasta / f'{offset:09d}.jsonl.gz'
    if path.exists():
        raise FileExistsError(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    if temp.exists():
        raise FileExistsError(f'Ficheiro temporário antigo: {temp}')
    try:
        with gzip.open(temp, 'wt', encoding='utf-8') as f:
            for row in registos:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def ler_paginas(pasta: Path):
    for path in sorted(pasta.glob('*.jsonl.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for linha in f:
                if linha.strip():
                    yield json.loads(linha)


def inventario_paginas(pasta: Path):
    arquivos = sorted(pasta.glob('*.jsonl.gz'))
    # Detecta buracos; nunca saltar páginas sem saber se foram recolhidas.
    for i, arq in enumerate(arquivos):
        esperado = i * PAGE_SIZE
        if int(arq.name.split('.', 1)[0]) != esperado:
            raise RuntimeError(f'Falta página {esperado} na pasta {pasta}')
    vistos = set()
    for row in ler_paginas(pasta):
        vistos.add(row['sha_original'])
    return len(arquivos) * PAGE_SIZE, vistos


def publicar(pasta: Path, saida: Path, limite: int):
    seen = set()
    contagem = 0
    parcial = saida.with_name(saida.name + '.partial')
    if parcial.exists():
        raise FileExistsError(f'Existe uma publicação parcial anterior: {parcial}')
    saida.parent.mkdir(parents=True, exist_ok=True)
    try:
        with gzip.open(parcial, 'wt', encoding='utf-8') as out:
            for row in ler_paginas(pasta):
                sha = row['sha_original']
                if sha in seen:
                    continue
                seen.add(sha)
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                contagem += 1
                if limite and contagem >= limite:
                    break
        if not contagem:
            raise RuntimeError('O servidor não devolveu histórias válidas; ficheiro final não criado.')
        os.replace(parcial, saida)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    return contagem


def recolher(saida: Path, limite: int, *, pedir=pedir_pagina, lotes_log: int = 10,
             max_paginas: int = 0, intervalo: float = 0):
    if limite < 1:
        raise ValueError('A meta de histórias deve ser positiva.')
    if intervalo < 0:
        raise ValueError('intervalo não pode ser negativo')
    if saida.exists():
        raise FileExistsError(f'O ficheiro final já existe: {saida}. Não vou substituí-lo.')
    pasta = saida.with_name(saida.name + '.pages')
    offset, vistos = inventario_paginas(pasta)
    if offset:
        print(f'A retomar: {offset} linhas de origem consultadas; {len(vistos)} histórias únicas.', flush=True)
    novas_paginas = 0
    acabou_fonte = False
    while len(vistos) < limite:
        if max_paginas and novas_paginas >= max_paginas:
            break
        if intervalo:
            time.sleep(intervalo)
        resp = pedir(offset, PAGE_SIZE)
        linhas = resp['rows']
        if not linhas:
            acabou_fonte = True
            break
        recolhidos = []
        for item in linhas:
            idx = item.get('row_idx')
            row = item.get('row')
            if not isinstance(idx, int) or not isinstance(row, dict):
                raise RuntimeError(f'Estrutura inesperada na página {offset}: {str(item)[:140]}')
            if idx < offset or idx >= offset + PAGE_SIZE:
                raise RuntimeError(f'Índice inesperado na página {offset}: {idx}')
            reg = registo_da_linha(row, idx)
            if reg is not None:
                recolhidos.append(reg)
        escrever_pagina(pasta, offset, recolhidos)
        for reg in recolhidos:
            vistos.add(reg['sha_original'])
        novas_paginas += 1
        offset += PAGE_SIZE
        if novas_paginas % lotes_log == 0:
            print(f'Linhas consultadas: {offset}; histórias únicas válidas: {len(vistos)}', flush=True)
        if len(linhas) < PAGE_SIZE:
            acabou_fonte = True
            break
    if max_paginas and novas_paginas >= max_paginas and len(vistos) < limite:
        print(f'Páginas guardadas. Ainda faltam {limite-len(vistos)} histórias. '
              f'Volta a executar o mesmo comando para retomar.', flush=True)
        return {'publicado': False, 'paginas_novas': novas_paginas, 'unicas': len(vistos)}
    if not vistos:
        raise RuntimeError('Nenhuma história válida. Verifica o acesso à API e os campos retornados.')
    contagem = publicar(pasta, saida, limite)
    return {'publicado': True, 'historias': contagem, 'meta': limite,
            'meta_atingida': contagem >= limite, 'fim_da_fonte': acabou_fonte,
            'paginas_novas': novas_paginas, 'ficheiro': str(saida)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('dados/corpus_ptpt/historias/raw/historinhas.jsonl.gz'))
    ap.add_argument('--max-rows', type=int, default=60000, help='Número de histórias distintas e válidas a recolher')
    ap.add_argument('--max-paginas', type=int, default=0, help='Limitar páginas por execução; permite retomar')
    ap.add_argument('--intervalo', type=float, default=5.0,
                    help='Segundos entre pedidos /rows (por omissão 5, para evitar HTTP 429)')
    ap.add_argument('--pausa-429', type=float, default=120.0,
                    help='Espera mínima inicial quando o servidor devolve HTTP 429')
    args = ap.parse_args(argv)
    if args.intervalo < 0 or args.pausa_429 < 0:
        ap.error('Os intervalos de espera não podem ser negativos.')
    print(json.dumps(recolher(args.out, args.max_rows, max_paginas=args.max_paginas,
                             intervalo=args.intervalo,
                             pedir=lambda offset, length: pedir_pagina(
                                 offset, length, pausa_429=args.pausa_429)),
                     ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()