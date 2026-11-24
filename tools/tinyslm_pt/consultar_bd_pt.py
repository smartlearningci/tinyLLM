#!/usr/bin/env python3
"""Consulta a BD de receitas sem LLM nem SQL gerado pelo modelo.

A aplicacao escolhe a receita. Uma alternativa geral nunca e tratada como
validada para a receita escolhida.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from contextlib import closing

from criar_bd_pt import chave


def abrir(bd: Path) -> sqlite3.Connection:
    if not bd.is_file():
        raise FileNotFoundError(f"Base nao encontrada: {bd}. Executa primeiro criar_bd_pt.py")
    db = sqlite3.connect(bd.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def listar_receitas(bd: Path, termo: str = "", origem: str = "", estado: str = "", limite: int = 30, offset: int = 0) -> list[dict]:
    conditions, args = [], []
    if termo:
        escaped = chave(termo).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("titulo_chave LIKE ? ESCAPE '\\'")
        args.append("%" + escaped + "%")
    if origem:
        conditions.append("origem=?")
        args.append(origem)
    if estado:
        conditions.append("estado=?")
        args.append(estado)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with closing(abrir(bd)) as db:
        tem_alertas = db.execute("SELECT 1 FROM sqlite_master WHERE name='alertas'").fetchone()
        contar_alertas = "(SELECT COUNT(*) FROM alertas a WHERE a.receita_id=receitas.id)" if tem_alertas else "0"
        rows = db.execute(
            "SELECT id,titulo,origem,estado,duplicado_de," + contar_alertas + " AS avisos FROM receitas" + where +
            " ORDER BY titulo_chave,id LIMIT ? OFFSET ?", (*args, max(1, min(limite, 100)), max(0, offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def obter_receita(bd: Path, receita_id: str) -> dict | None:
    with closing(abrir(bd)) as db:
        row = db.execute(
            "SELECT id,titulo,origem,idioma,categoria,url,estado,duplicado_de,original_json FROM receitas WHERE id=?",
            (receita_id,),
        ).fetchone()
        if not row:
            return None
        dados = dict(row)
        dados["ingredientes"] = []
        dados["preparacao"] = []
        dados["extras"] = []
        existe_alertas = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alertas'").fetchone()
        dados["alertas"] = ([dict(r) for r in db.execute(
            "SELECT codigo,mensagem FROM alertas WHERE receita_id=? ORDER BY codigo", (receita_id,)
        )] if existe_alertas else [])
        for parte in db.execute(
            "SELECT tipo,titulo_secao,texto FROM partes WHERE receita_id=? ORDER BY tipo,numero", (receita_id,)
        ):
            item = {"secao": parte["titulo_secao"], "texto": parte["texto"]}
            dados[parte["tipo"]].append(item)
        return dados


def resumo_bd(bd: Path) -> dict:
    with closing(abrir(bd)) as db:
        existe_alertas = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alertas'").fetchone()
        return {
            "total": db.execute("SELECT COUNT(*) FROM receitas").fetchone()[0],
            "origens": dict(db.execute("SELECT origem,COUNT(*) FROM receitas GROUP BY origem").fetchall()),
            "estados": dict(db.execute("SELECT estado,COUNT(*) FROM receitas GROUP BY estado").fetchall()),
            "alertas": dict(db.execute("SELECT codigo,COUNT(*) FROM alertas GROUP BY codigo").fetchall()) if existe_alertas else {},
            "a_rever": db.execute("SELECT COUNT(DISTINCT receita_id) FROM alertas").fetchone()[0] if existe_alertas else 0,
        }


def procurar(bd: Path, receita_id: str | None, tipo: str, termo: str = "", para: str = "") -> dict:
    if tipo not in ("ingrediente", "preparo", "tecnica", "alternativa"):
        return {"estado": "TIPO_DESCONHECIDO"}
    with closing(abrir(bd)) as db:
        if receita_id:
            if not db.execute("SELECT 1 FROM receitas WHERE id=?", (receita_id,)).fetchone():
                return {"estado": "RECEITA_DESCONHECIDA"}
        elif tipo in ("ingrediente", "preparo", "alternativa"):
            return {"estado": "RECEITA_NECESSARIA"}

        if tipo in ("ingrediente", "preparo"):
            secao = "ingredientes" if tipo == "ingrediente" else "preparacao"
            linhas = db.execute(
                "SELECT texto FROM partes WHERE receita_id=? AND tipo=? ORDER BY numero",
                (receita_id, secao),
            ).fetchall()
            encontrados = [r["texto"] for r in linhas if not termo or chave(termo) in chave(r["texto"])]
            return {"estado": "ENCONTRADO" if encontrados else "SEM_DADOS",
                    "dados": encontrados[:10], "total_correspondencias": len(encontrados)}

        linhas = db.execute("SELECT * FROM apoio WHERE tipo=?", (tipo,)).fetchall()
        encontrados = [dict(r) for r in linhas if chave(r["termo"]) == chave(termo)]
        if tipo == "alternativa":
            if para:
                encontrados = [r for r in encontrados if chave(r["equivalente"]) == chave(para)]
            if not encontrados:
                return {"estado": "SEM_ALTERNATIVA_REGISTADA", "dados": []}
            # Nao supor que uma troca generica e segura nesta receita.
            return {"estado": "SUGESTAO_GERAL_CONDICIONAL", "dados": encontrados}
        return {"estado": "ENCONTRADO" if encontrados else "SEM_DADOS", "dados": encontrados}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bd", type=Path, default=Path("dados/tiny_pt.sqlite"))
    p.add_argument("--listar", action="store_true", help="Pesquisar receitas pelo nome")
    p.add_argument("--origem", choices=["wikilivros", "afrodite"], default="")
    p.add_argument("--estado", choices=["completa", "parcial", "incompleta"], default="")
    p.add_argument("--receita-id", default="")
    p.add_argument("--tipo", choices=["ingrediente", "preparo", "tecnica", "alternativa"])
    p.add_argument("--termo", default="")
    p.add_argument("--para", default="", help="Alternativa especifica: ex. sacarina")
    args = p.parse_args()
    if args.listar:
        resultado = listar_receitas(args.bd, args.termo, args.origem, args.estado)
    elif args.tipo:
        resultado = procurar(args.bd, args.receita_id or None, args.tipo, args.termo, args.para)
    else:
        resultado = resumo_bd(args.bd)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()