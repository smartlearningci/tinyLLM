#!/usr/bin/env python3
"""Extratores locais de obras PT-PT em TEI/XML, EPUB e TXT.

Não pressupõe acesso livre: o utilizador coloca os arquivos com direitos de uso
confirmados na pasta raw/. Não executa pedidos web nem extrai ZIPs para disco.
"""
from __future__ import annotations

import argparse
import hashlib
import time
from urllib.request import Request, urlopen
from urllib.parse import unquote
import gzip
import html
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from build_ptpt import ROOT, digest, ingere_documentos, normalizar


def local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def texto_xml(node: ET.Element) -> str:
    # Ignorar notas editoriais/metadata de ficheiros TEI e HTML de EPUB.
    ignorar = {'note', 'head', 'figure', 'fw', 'pb', 'script', 'style', 'nav', 'aside'}
    textos = []
    def visitar(n):
        if local(n.tag).lower() in ignorar:
            if n.tail:
                textos.append(n.tail)
            return
        if n.text:
            textos.append(n.text)
        for child in n:
            visitar(child)
        if n.tail:
            textos.append(n.tail)
        if local(n.tag).lower() in {'p', 'l', 'div', 'seg', 's', 'u'}:
            textos.append('\n')
    visitar(node)
    return normalizar(html.unescape(''.join(textos)))


def dividir_texto(texto: str, max_chars: int = 12000):
    """Blocos em limites de parágrafo/frase, sempre menores que max_chars.

    A validação é feita em unidades da obra; a chave 'group' permanece igual.
    """
    if max_chars < 500:
        raise ValueError('max_chars >= 500')
    texto = normalizar(texto)
    paragrafos = [x.strip() for x in re.split(r'\n\s*\n|\n', texto) if x.strip()]
    atual = ''
    for par in paragrafos:
        partes = [par[i:i+max_chars] for i in range(0, len(par), max_chars)]
        for parte in partes:
            if atual and len(atual) + len(parte) + 2 > max_chars:
                yield atual
                atual = ''
            atual = (atual + '\n\n' + parte).strip() if atual else parte
    if atual:
        yield atual


def doc_bloco(fonte: str, group: str, texto: str, max_chars: int):
    for n, bloco in enumerate(dividir_texto(texto, max_chars)):
        yield {'id': f'{fonte}:{digest(group)[:14]}:{n:05d}', 'group': group, 'text': bloco}


def tei_eltec(path: Path) -> str:
    root = ET.parse(path).getroot()
    body = next((x for x in root.iter() if local(x.tag) == 'body'), None)
    if body is None:
        raise ValueError(f'Não há corpo TEI <body> em {path}')
    return texto_xml(body)


def eltec_docs(pasta: Path, max_chars=12000):
    for path in sorted(pasta.rglob('*.xml')):
        # Evitar documentos de metadados, manter apenas ficheiros TEI com body.
        try:
            texto = tei_eltec(path)
        except ValueError:
            continue
        rel = str(path.relative_to(pasta))
        yield from doc_bloco('eltec_por', 'eltec_por:' + rel, texto, max_chars)


def parlamint_docs(pasta: Path, max_chars=12000):
    """Extrai blocos de discursos <u> de XML TEI de ParlaMint-PT.

    Só documentos onde se encontra <u>, sem contar metadata ou raiz.
    """
    for path in sorted(pasta.rglob('*.xml')):
        rel = str(path.relative_to(pasta))
        if 'ana' in path.parts or '.ana.' in path.name:
            continue
        i = 0
        # Processamento de XML sem carregar sessões inteiras em memória.
        for event, node in ET.iterparse(path, events=('end',)):
            if local(node.tag) != 'u':
                continue
            corpo = texto_xml(node)
            if corpo:
                i += 1
                group = 'parlamint_pt:' + rel
                for bloco in doc_bloco('parlamint_pt', group + f':u{i}', corpo, max_chars):
                    # Mantém toda a sessão parlamentar no mesmo split.
                    bloco['group'] = group
                    yield bloco
            node.clear()


def _epub_spine(zipf: zipfile.ZipFile):
    """Lê o spine EPUB para manter a ordem textual, não a ordem ZIP."""
    container = ET.fromstring(zipf.read('META-INF/container.xml'))
    rootfile = next((n.get('full-path') for n in container.iter()
                     if local(n.tag) == 'rootfile'), None)
    if not rootfile:
        raise ValueError('EPUB sem rootfile OPF')
    opf = ET.fromstring(zipf.read(rootfile))
    manifest = {n.get('id'): n.get('href') for n in opf.iter() if local(n.tag) == 'item'}
    spine = [n.get('idref') for n in opf.iter() if local(n.tag) == 'itemref']
    base = PurePosixPath(rootfile).parent
    for ref in spine:
        href = manifest.get(ref)
        if not href or not href.lower().split('#')[0].endswith(('.xhtml', '.html', '.htm')):
            continue
        clean = unquote(href.split('#')[0].split('?')[0])
        name = str(base / clean)
        if '..' in PurePosixPath(name).parts:
            raise ValueError('EPUB contém caminho inseguro')
        yield name


def texto_epub(path: Path) -> str:
    textos = []
    with zipfile.ZipFile(path) as z:
        for name in _epub_spine(z):
            root = ET.fromstring(z.read(name))
            body = next((n for n in root.iter() if local(n.tag) == 'body'), None)
            if body is not None:
                txt = texto_xml(body)
                if txt:
                    textos.append(txt)
    if not textos:
        raise ValueError(f'EPUB sem texto extraível: {path}')
    return '\n\n'.join(textos)


def adamastor_docs(pasta: Path, max_chars=12000):
    for path in sorted(pasta.rglob('*.epub')):
        rel = str(path.relative_to(pasta))
        yield from doc_bloco('adamastor', 'adamastor:' + rel, texto_epub(path), max_chars)


def textos_docs(pasta: Path, source: str, max_chars=12000):
    for path in sorted(pasta.rglob('*.txt')):
        rel = str(path.relative_to(pasta))
        yield from doc_bloco(source, f'{source}:{rel}', path.read_text(encoding='utf-8-sig'), max_chars)


ELTEC_LEVEL1_API = 'https://api.github.com/repos/COST-ELTeC/ELTeC-por/contents/level1?ref=master'


def git_blob_sha(data: bytes):
    h = hashlib.sha1()
    h.update(f'blob {len(data)}\0'.encode('ascii'))
    h.update(data)
    return h.hexdigest()


def obter_eltec(out_dir: Path, *, limit=0, listing=None, transfer=None):
    """Descarrega só as ~100 obras level1, nunca o arquivo GitHub de 400 MB+.

    Verifica o hash Git de cada ficheiro. Reexecutar é seguro se já existe
    cópia íntegra. Usa uma só chamada API para listar; restantes via raw.
    """
    def fetch(url):
        if not url.startswith(('https://api.github.com/',
                               'https://raw.githubusercontent.com/')):
            raise ValueError('URL externa não autorizada para ELTeC')
        req = Request(url, headers={'User-Agent':'tinyslm-ptpt-dataset/1.0'})
        with urlopen(req, timeout=120) as resp:
            return resp.read()
    fs = transfer or fetch
    import json
    items = listing if listing is not None else json.loads(fs(ELTEC_LEVEL1_API))
    if not isinstance(items, list):
        raise ValueError('A API GitHub não devolveu uma lista de ficheiros level1.')
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {'novos': 0, 'ja_existiam': 0, 'ficheiros_previstos': 0}
    for item in items:
        if item.get('type') != 'file' or not str(item.get('name','')).endswith('.xml'):
            continue
        name, sha = item['name'], item['sha']
        path = out_dir / name
        stats['ficheiros_previstos'] += 1
        if path.exists():
            if git_blob_sha(path.read_bytes()) != sha:
                raise ValueError('A cópia local não coincide com o GitHub: ' + str(path))
            stats['ja_existiam'] += 1
        else:
            blob = fs(item['download_url'])
            if git_blob_sha(blob) != sha:
                raise ValueError('Checksum incorreto no download: ' + name)
            path.write_bytes(blob)
            stats['novos'] += 1
        if limit and stats['novos'] + stats['ja_existiam'] >= limit:
            break
    if stats['ficheiros_previstos'] == 0:
        raise ValueError('Não foram encontrados ficheiros XML level1')
    return stats


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tipo', choices=['eltec', 'parlamint', 'adamastor', 'txt', 'obter-eltec'])
    p.add_argument('--input-dir', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--source', default='textos_ptpt', help='Aplicável apenas a txt')
    p.add_argument('--max-chars', type=int, default=12000)
    p.add_argument('--limite', type=int, default=0)
    a = p.parse_args(argv)
    if a.tipo == 'obter-eltec':
        result = obter_eltec(a.input_dir or (ROOT / 'raw/eltec_level1'), limit=a.limite)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not a.input_dir or not a.out:
        p.error('Os parâmetros --input-dir e --out são obrigatórios neste modo')
    if not a.input_dir.is_dir():
        p.error('A pasta de entrada não existe: ' + str(a.input_dir))
    it = {'eltec': lambda: eltec_docs(a.input_dir, a.max_chars),
          'parlamint': lambda: parlamint_docs(a.input_dir, a.max_chars),
          'adamastor': lambda: adamastor_docs(a.input_dir, a.max_chars),
          'txt': lambda: textos_docs(a.input_dir, a.source, a.max_chars)}[a.tipo]()
    source = {'eltec':'eltec_por', 'parlamint':'parlamint_pt',
              'adamastor':'adamastor', 'txt':a.source}[a.tipo]
    result = ingere_documentos(it, a.out, source, min_palavras=35)
    if result['guardados'] == 0:
        raise RuntimeError('Não foi extraído texto válido. Confirma formato/ficheiros.')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()