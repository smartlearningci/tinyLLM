#!/usr/bin/env python3
"""Navegador local para consultar as receitas em PT/PT-BR, sem instalar pacotes."""
from __future__ import annotations

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextlib import closing
from urllib.parse import parse_qs, quote, urlsplit

from consultar_bd_pt import listar_receitas, obter_receita, resumo_bd, abrir

CSS = """
body{font-family:system-ui,-apple-system,sans-serif;line-height:1.5;max-width:980px;
 margin:2rem auto;padding:0 1rem;color:#242424;background:#fafaf8}
h1,h2{line-height:1.2}a{color:#136b78;text-decoration:none}a:hover{text-decoration:underline}
header{margin-bottom:1.2rem}small,.muted{color:#666}form,.panel{background:white;border:1px solid #ddd;
 border-radius:9px;padding:1rem;margin:1rem 0}.filters{display:flex;gap:.6rem;flex-wrap:wrap;align-items:end}
label{display:block;font-size:.85rem;color:#555}input,select,button{font:inherit;padding:.45rem .6rem;
 border:1px solid #bbb;border-radius:6px}button{background:#166978;color:white;border:0;cursor:pointer}
article{background:white;border:1px solid #e0e0e0;border-radius:7px;padding:.7rem 1rem;
 margin:.5rem 0}.pill{display:inline-block;border:1px solid #ccc;border-radius:99px;
 font-size:.75rem;padding:.1rem .5rem;color:#555;margin-left:.3rem}
li{margin:.35rem 0}ul,ol{padding-left:1.6rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}.warning{color:#8b4304}footer{margin:2rem 0;color:#777;font-size:.85rem}
"""


def e(v: object) -> str:
    return html.escape(str(v or ""), quote=True)


def layout(title: str, content: str) -> str:
    return ("<!doctype html><html lang='pt'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{e(title)} · TinySLM</title><style>{CSS}</style></head><body>"
            "<header><a href='/'><strong>TinySLM</strong> — Base culinária PT + BR</a></header>"
            f"{content}<footer>Consulta local. Dados de origem preservados; 'completa' não significa validada.</footer>"
            "</body></html>")


def inicio(bd: Path, params: dict[str, list[str]]) -> str:
    def g(k: str) -> str:
        return params.get(k, [""])[0]
    q, origem, estado = g("q"), g("origem"), g("estado")
    try:
        pagina = max(0, int(g("pagina") or "0"))
    except ValueError:
        pagina = 0
    info = resumo_bd(bd)
    resultados = listar_receitas(bd, q, origem, estado, limite=30, offset=pagina*30)
    options_origem = "".join(f'<option value="{x}" {"selected" if origem==x else ""}>{label}</option>'
                             for x, label in (("", "Todas"), ("wikilivros", "Wikilivros"), ("afrodite", "Afrodite")))
    options_estado = "".join(f'<option value="{x}" {"selected" if estado==x else ""}>{label}</option>'
                             for x, label in (("", "Todos"), ("completa", "Completa"),
                                              ("parcial", "Parcial"), ("incompleta", "Incompleta")))
    content = ("<h1>Pesquisar receitas</h1>"
               f"<p class='muted'>{info['total']:,} registos · "
               f"{info['estados'].get('completa', 0):,} com ingredientes e preparação · "
               f"{info['a_rever']:,} registos com avisos</p>"
               "<form method='get' action='/'><div class='filters'>"
               f"<div><label>Nome da receita</label><input name='q' value='{e(q)}' placeholder='Ex.: bolo de cenoura'></div>"
               f"<div><label>Origem</label><select name='origem'>{options_origem}</select></div>"
               f"<div><label>Estado</label><select name='estado'>{options_estado}</select></div>"
               "<button type='submit'>Pesquisar</button></div></form>"
               "<p><a href='/apoio'>Consultar técnicas e substituições</a></p>"
               f"<h2>Resultados</h2><p class='muted'>{len(resultados)} nesta página</p>")
    for r in resultados:
        duplicado = '<span class="pill">possível duplicado</span>' if r['duplicado_de'] else ''
        rever = '<span class="pill warning">rever</span>' if r['avisos'] else ''
        content += (f"<article><a href='/?receita={quote(r['id'])}'><strong>{e(r['titulo'])}</strong></a>"
                    f"<span class='pill'>{e(r['origem'])}</span><span class='pill'>{e(r['estado'])}</span>"
                    f"{duplicado}{rever}</article>")
    if not resultados:
        content += "<p>Nenhuma receita encontrada.</p>"
    if len(resultados) == 30:
        content += ("<p><a href='/?q=" + quote(q) + "&origem=" + quote(origem) + "&estado=" +
                    quote(estado) + "&pagina=" + str(pagina+1) + "'>Página seguinte</a></p>")
    if pagina:
        content += ("<p><a href='/?q=" + quote(q) + "&origem=" + quote(origem) + "&estado=" +
                    quote(estado) + "&pagina=" + str(pagina-1) + "'>Página anterior</a></p>")
    return layout("Receitas", content)


def detalhe(bd: Path, rid: str) -> str:
    reg = obter_receita(bd, rid)
    if not reg:
        return layout("Não encontrada", "<h1>Receita não encontrada</h1><p><a href='/'>Voltar</a></p>")
    content = (f"<p><a href='/'>← Voltar à pesquisa</a></p><h1>{e(reg['titulo'])}</h1>"
               f"<p>Origem: {e(reg['origem'])} · Idioma: {e(reg['idioma'])} · "
               f"Estado: <strong>{e(reg['estado'])}</strong></p>"
               f"<p class='muted'>ID: <code>{e(reg['id'])}</code></p>")
    if reg['duplicado_de']:
        content += "<p class='warning'>Este registo poderá ser duplicado exato de outro.</p>"
    if reg["alertas"]:
        content += "<section class='panel'><h2>Avisos de revisão</h2><ul>"
        for aviso in reg["alertas"]:
            content += f"<li class='warning'>{e(aviso['mensagem'])}</li>"
        content += "</ul></section>"
    if reg['estado'] != 'completa':
        content += "<p class='warning'>A receita não tem todos os campos estruturados. Consulta também a informação adicional.</p>"
    if reg['url'].startswith(('https://', 'http://')):
        content += f"<p><a href='{e(reg['url'])}' target='_blank' rel='noopener noreferrer'>Ver fonte original</a></p>"
    for tipo, titulo, tag in (("ingredientes", "Ingredientes", "ul"),
                              ("preparacao", "Preparação", "ol"),
                              ("extras", "Informação adicional", "ul")):
        content += f"<section class='panel'><h2>{titulo}</h2>"
        if not reg[tipo]:
            content += "<p class='muted'>Não há dados estruturados nesta secção.</p>"
        else:
            content += f"<{tag}>"
            for x in reg[tipo]:
                sec = f"<strong>{e(x['secao'])}:</strong> " if x['secao'] else ""
                content += f"<li>{sec}{e(x['texto'])}</li>"
            content += f"</{tag}>"
        content += "</section>"
    content += ("<details class='panel'><summary>Ver texto original da fonte</summary>"
                f"<pre>{e(reg['original_json'])}</pre></details>")
    return layout(reg['titulo'], content)


def apoio(bd: Path) -> str:
    content = "<p><a href='/'>← Voltar</a></p><h1>Técnicas e alternativas</h1>"
    with closing(abrir(bd)) as conn:
        for tipo, titulo in (("tecnica", "Técnicas"), ("alternativa", "Alternativas gerais")):
            content += f"<h2>{titulo}</h2>"
            if tipo == "alternativa":
                content += "<p class='warning'>São ideias condicionais, NÃO substituições validadas para receitas concretas.</p>"
            for r in conn.execute("SELECT * FROM apoio WHERE tipo=? ORDER BY termo", (tipo,)):
                destino = f" → {e(r['equivalente'])}" if r['equivalente'] else ""
                restricao = f"<p class='warning'>{e(r['restricao'])}</p>" if r['restricao'] else ""
                content += (f"<article><strong>{e(r['termo'])}{destino}</strong><p>{e(r['explicacao'])}</p>"
                            f"{restricao}</article>")
    return layout("Técnicas e alternativas", content)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bd", type=Path, default=Path("dados/tiny_pt.sqlite"))
    p.add_argument("--porta", type=int, default=8767)
    args = p.parse_args()
    if not args.bd.is_file():
        p.error(f"Base não encontrada: {args.bd}. Primeiro executa criar_bd_pt.py")
    bd = args.bd.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            params = parse_qs(url.query, keep_blank_values=True)
            try:
                if url.path == "/apoio":
                    body = apoio(bd)
                elif url.path == "/":
                    rid = params.get("receita", [""])[0]
                    body = detalhe(bd, rid) if rid else inicio(bd, params)
                else:
                    self.send_error(404)
                    return
                raw = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", args.porta), Handler)
    print(f"Abre no navegador: http://127.0.0.1:{args.porta}")
    print("Para terminar, prime Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()