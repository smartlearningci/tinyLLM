#!/usr/bin/env python3
"""Prepara uma SQLite de receitas PT/PT-BR a partir de Wikilivros e Afrodite.

Sem dependencias externas. Mantem TODO o registo original e separa os dados
estruturados sem inventar ingredientes ou passos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
import urllib.request
from pathlib import Path

FONTES = {
    "wikilivros": "https://raw.githubusercontent.com/denisevitoriano/tech_challenge_fase_04/main/data/processed/receitas.jsonl",
    "afrodite": "https://raw.githubusercontent.com/adrianosferreira/afrodite.json/master/afrodite.json",
}
NOMES = {"wikilivros": "receitas_wikilivros.jsonl", "afrodite": "afrodite.json"}


def limpo(valor: object) -> str:
    return re.sub(r"\s+", " ", str(valor or "").replace("\xa0", " ")).strip()


def chave(valor: object) -> str:
    texto = unicodedata.normalize("NFD", limpo(valor).casefold())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def identificador(prefixo: str, texto: str) -> str:
    return prefixo + ":" + hashlib.sha256(texto.encode("utf-8")).hexdigest()[:20]


def itens(lista: object) -> list[str]:
    if isinstance(lista, str):
        lista = [lista]
    if not isinstance(lista, list):
        return []
    return [v for x in lista if (v := limpo(x))]


def baixar(nome: str, pasta: Path) -> Path:
    """Descarrega uma vez, com escrita atomica para nao guardar ficheiro parcial."""
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / NOMES[nome]
    if destino.exists():
        return destino
    temporario = destino.with_name(destino.name + ".part")
    pedido = urllib.request.Request(FONTES[nome], headers={"User-Agent": "TinySLM-Research/1.0"})
    try:
        with urllib.request.urlopen(pedido, timeout=90) as resposta, temporario.open("wb") as saida:
            while bloco := resposta.read(1024 * 1024):
                saida.write(bloco)
        if temporario.stat().st_size < 100:
            raise ValueError(f"Fonte descarregada vazia: {nome}")
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
    return destino


def extrair_wikilivros(caminho: Path):
    with caminho.open(encoding="utf-8") as f:
        for numero, linha in enumerate(f, 1):
            if not linha.strip():
                continue
            reg = json.loads(linha)
            titulo = limpo(reg.get("titulo"))
            ing, prep = itens(reg.get("ingredientes")), itens(reg.get("preparo"))
            url = limpo(reg.get("fonte_url"))
            rid = identificador("wiki", f"{numero}|{url}|{titulo}")
            yield rid, "wikilivros", "pt", titulo, limpo(reg.get("categoria")), url, ing, prep, [], reg


def extrair_afrodite(caminho: Path):
    with caminho.open(encoding="utf-8") as f:
        dados = json.load(f)
    if not isinstance(dados, list):
        raise ValueError("O ficheiro Afrodite nao contem uma lista JSON.")
    for numero, reg in enumerate(dados, 1):
        titulo = limpo(reg.get("nome"))
        ing, prep, extras = [], [], []
        for parte in reg.get("secao") or []:
            nome = limpo(parte.get("nome"))
            textos = itens(parte.get("conteudo"))
            k = chave(nome)
            if "ingrediente" in k:
                ing.extend(textos)
            elif "preparo" in k or "preparacao" in k or "modo de fazer" in k:
                prep.extend(textos)
            else:
                extras.extend((nome, texto) for texto in textos)
        oid = (reg.get("_id") or {}).get("$oid")
        rid = "afro:" + str(oid) if oid else identificador("afro", f"{numero}|{titulo}")
        yield rid, "afrodite", "pt-BR", titulo, "", "", ing, prep, extras, reg


ESQUEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE receitas (
    id TEXT PRIMARY KEY,
    origem TEXT NOT NULL,
    idioma TEXT NOT NULL,
    titulo TEXT NOT NULL,
    titulo_chave TEXT NOT NULL,
    categoria TEXT,
    url TEXT,
    estado TEXT NOT NULL,
    duplicado_de TEXT,
    grupo TEXT NOT NULL,
    original_json TEXT NOT NULL
);
CREATE TABLE partes (
    receita_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    numero INTEGER NOT NULL,
    titulo_secao TEXT,
    texto TEXT NOT NULL,
    PRIMARY KEY (receita_id, tipo, numero),
    FOREIGN KEY (receita_id) REFERENCES receitas(id)
);
CREATE TABLE apoio (
    tipo TEXT NOT NULL,
    termo TEXT NOT NULL,
    equivalente TEXT NOT NULL DEFAULT '',
    explicacao TEXT NOT NULL,
    restricao TEXT NOT NULL DEFAULT '',
    validado_para_receita INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(tipo, termo, equivalente)
);
CREATE INDEX idx_titulo ON receitas(titulo_chave);
CREATE INDEX idx_origem_estado ON receitas(origem, estado);
CREATE INDEX idx_partes ON partes(receita_id, tipo);
"""


def criar(destino: Path, fontes: dict[str, Path], apoio_file: Path) -> dict:
    if destino.exists():
        raise FileExistsError(f"A base ja existe: {destino}. Nao sera substituida.")
    # Ler apoio antes de criar a BD; se estiver errado nao deixa um ficheiro inutil.
    apoio = json.loads(apoio_file.read_text(encoding="utf-8"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(destino)
    resumo = {
        "total": 0, "por_origem": {}, "estados": {"completa": 0, "parcial": 0, "incompleta": 0},
        "duplicados_exatos": 0, "apoio": {},
        "nota": "Completa significa apenas >=2 ingredientes e >=1 instrucao; nao e validacao culinaria.",
    }
    vistos: dict[str, str] = {}
    try:
        db.executescript(ESQUEMA)
        for origem, ficheiro in fontes.items():
            if origem not in FONTES:
                raise ValueError(f"Origem nao suportada: {origem}")
            n = 0
            gerador = extrair_wikilivros(ficheiro) if origem == "wikilivros" else extrair_afrodite(ficheiro)
            for rid, src, idioma, titulo, categoria, url, ing, prep, extras, original in gerador:
                n += 1
                if len(ing) >= 2 and len(prep) >= 1:
                    estado = "completa"
                elif ing or prep or extras:
                    estado = "parcial"
                else:
                    estado = "incompleta"
                grupo = identificador("grupo", chave(titulo))
                # Apenas duplicados textualmente identicos; nao elimina variantes.
                assinatura = identificador("conteudo", chave(titulo) + "|" + "\n".join(chave(v) for v in ing + prep + [v for _, v in extras]))
                duplicado_de = vistos.get(assinatura)
                if duplicado_de:
                    resumo["duplicados_exatos"] += 1
                else:
                    vistos[assinatura] = rid
                db.execute("INSERT INTO receitas VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    rid, src, idioma, titulo, chave(titulo), categoria, url, estado, duplicado_de,
                    grupo, json.dumps(original, ensure_ascii=False),
                ))
                for tipo, valores in (
                    ("ingredientes", [(None, v) for v in ing]),
                    ("preparacao", [(None, v) for v in prep]),
                    ("extras", extras),
                ):
                    db.executemany("INSERT INTO partes VALUES(?,?,?,?,?)", (
                        (rid, tipo, numero, secao, texto)
                        for numero, (secao, texto) in enumerate(valores, 1)
                    ))
                resumo["estados"][estado] += 1
            resumo["por_origem"][origem] = n
            resumo["total"] += n
        for tipo, entradas in apoio.items():
            for entrada in entradas:
                db.execute("INSERT INTO apoio VALUES(?,?,?,?,?,0)", (
                    tipo, entrada["termo"], entrada.get("equivalente", ""),
                    entrada["explicacao"], entrada.get("restricao", ""),
                ))
            resumo["apoio"][tipo] = len(entradas)
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        destino.unlink(missing_ok=True)
        raise
    db.close()
    return resumo


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wikilivros", type=Path, help="Ficheiro JSONL local (opcional)")
    p.add_argument("--afrodite", type=Path, help="Ficheiro JSON local (opcional)")
    p.add_argument("--pasta-fontes", type=Path, default=Path("dados/fontes"))
    p.add_argument("--saida", type=Path, default=Path("dados/tiny_pt.sqlite"))
    p.add_argument("--apoio", type=Path, default=Path(__file__).with_name("apoio.json"))
    args = p.parse_args()
    fontes = {
        nome: (getattr(args, nome) or baixar(nome, args.pasta_fontes))
        for nome in FONTES
    }
    resultado = criar(args.saida, fontes, args.apoio)
    relatorio = args.saida.with_suffix(".relatorio.json")
    relatorio.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"\nBase: {args.saida}\nRelatorio: {relatorio}")


if __name__ == "__main__":
    main()