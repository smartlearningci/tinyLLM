#!/usr/bin/env python3
"""Exporta receitas normalizadas (sem inventar dados) para JSONL de trabalho."""
from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

from consultar_bd_pt import abrir


def exportar(bd: Path, destino: Path, completas: bool = True, incluir_duplicados: bool = False, excluir_alertas: bool = False) -> int:
    if destino.exists():
        raise FileExistsError(f"Já existe: {destino}. Não será substituído.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    filtros = []
    if completas:
        filtros.append("estado='completa'")
    if not incluir_duplicados:
        filtros.append("duplicado_de IS NULL")
    if excluir_alertas:
        filtros.append("NOT EXISTS (SELECT 1 FROM alertas a WHERE a.receita_id=receitas.id)")
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    count = 0
    temp = destino.with_suffix(destino.suffix + ".part")
    try:
        with closing(abrir(bd)) as conn, temp.open("w", encoding="utf-8") as out:
            existe_alertas = conn.execute("SELECT 1 FROM sqlite_master WHERE name='alertas'").fetchone()
            if excluir_alertas and not existe_alertas:
                raise ValueError("Esta BD não tem alertas de qualidade. Reconstrói com criar_bd_pt.py numa base nova.")
            for reg in conn.execute(
                "SELECT id,origem,idioma,titulo,categoria,url,estado,grupo,duplicado_de "
                "FROM receitas" + where + " ORDER BY id"
            ):
                item = dict(reg)
                item["alertas"] = ([dict(a) for a in conn.execute(
                    "SELECT codigo,mensagem FROM alertas WHERE receita_id=? ORDER BY codigo", (reg["id"],)
                )] if existe_alertas else [])
                item["ingredientes"] = []
                item["preparacao"] = []
                item["extras"] = []
                for p in conn.execute("SELECT tipo,titulo_secao,texto FROM partes "
                                      "WHERE receita_id=? ORDER BY tipo,numero", (reg["id"],)):
                    if p["tipo"] == "extras":
                        item["extras"].append({"secao": p["titulo_secao"], "texto": p["texto"]})
                    else:
                        item[p["tipo"]].append(p["texto"])
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        temp.replace(destino)
        return count
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bd", type=Path, default=Path("dados/tiny_pt.sqlite"))
    parser.add_argument("--saida", type=Path, default=Path("dados/receitas_pt_normalizadas.jsonl"))
    parser.add_argument("--todas", action="store_true", help="Também exporta incompletas e parciais")
    parser.add_argument("--incluir-duplicados", action="store_true")
    parser.add_argument("--excluir-alertas", action="store_true", help="Ignorar receitas com avisos de revisão")
    args = parser.parse_args()
    n = exportar(args.bd, args.saida, not args.todas, args.incluir_duplicados, args.excluir_alertas)
    print(f"Exportadas {n} receitas para {args.saida}")


if __name__ == "__main__":
    main()