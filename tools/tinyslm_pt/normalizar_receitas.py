"""Normalização conservadora de receitas PT e PT-BR, sem alterar o conteúdo factual.

Preserva a linguagem de origem e não inventa ingredientes ou instruções.
É intencionalmente independente do formato específico das fontes.
"""
from __future__ import annotations

import re

VERSAO = "1.2"


def compacto(valor: object) -> str:
    return re.sub(r"\s+", " ", str(valor or "").replace("\xa0", " ")).strip()


# Aplicado só aos passos, nunca ao início de uma quantidade de ingrediente.
NUMERO_PASSO = re.compile(r"^(?:(?:passo|etapa)\s*)?\d{1,3}\s*(?:[.)]|[-–—])\s*(?=[^\s\d])", flags=re.I)
# Algumas fontes colam o subtítulo ao marcador: "Berinjela1 - ...".
# Guardar o subtítulo como secção em vez de o deixar dentro do texto do passo.
TITULO_COM_NUMERO = re.compile(
    r"^(?P<secao>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÀ-ÿ /()]{1,45}?)\s*"
    r"(?P<numero>\d{1,3})\s*[-–—.)]\s*(?=[^\s\d])"
)
# Separador de ingredientes concatenados, aplicado só a linhas com subtítulo
# confirmado na preparação (ex.: "Maionese- 1 fio ...- 1 pimentão...").
SEPARADOR_INGREDIENTES = re.compile(r"[-–—]\s+(?=\d|[½¼¾]|[A-ZÁÉÍÓÚÂÊÔÃÕÇ])")
MARCADOR_ITEM = re.compile(r"^(?:[•*]\s*|[-–—]\s+)")
UNIDADE_JUNTA = re.compile(r"(\d)(kg|mg|g|ml|l)\b", re.I)
FIM_FRASE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])")
ABREVIATURAS = re.compile(r"\b(?:min|aprox|ex|etc|sr|sra|dr|dra)\.$", re.I)
TEMPO_APROXIMADO = re.compile(r"\(\s*\+\s*/\s*-\s*(\d+(?:[,.]\d+)?)\s+([^)]{1,36})\)")
MARCADORES_INTERIORES = re.compile(r"[.;:]\s+\d{1,3}\s*[-.)]\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]")
RISCO_BRASAS = re.compile(r"\bcarv[aã]o\b[^.]{0,80}\b(?:brasa|acend|chama|aceso)\b|\b(?:brasa|acend|chama|aceso)\b[^.]{0,80}\bcarv[aã]o\b", re.I)
CABEÇALHOS_INGREDIENTES = {"massa", "recheio", "cobertura", "calda", "para o recheio", "para a massa", "ingredientes", "molho"}


def normalizar_ingrediente(texto: object) -> str:
    s = compacto(texto)
    s = MARCADOR_ITEM.sub("", s)
    # Remover só marcadores de lista inequívocos, sem converter unidades nem quantidades.
    return UNIDADE_JUNTA.sub(r"\1 \2", s)


def obter_secao_passo(texto: object) -> tuple[str | None, str]:
    s = compacto(texto)
    resultado = TITULO_COM_NUMERO.match(s)
    if resultado:
        # Retirar só o subtítulo; o número será tratado por normalizar_passo.
        return compacto(resultado.group("secao")), s[resultado.start("numero"):]
    return None, s


def normalizar_passo(texto: object) -> str:
    _, s = obter_secao_passo(texto)
    s = NUMERO_PASSO.sub("", s)
    s = TEMPO_APROXIMADO.sub(r"(aproximadamente \1 \2)", s)
    return UNIDADE_JUNTA.sub(r"\1 \2", s)


def dividir_preparacao_com_seccoes(textos: list[str]) -> list[tuple[str | None, str]]:
    """Divide frases e mantém o subtítulo até aparecer outro subtítulo."""
    saida: list[tuple[str | None, str]] = []
    secao_atual: str | None = None
    for texto in textos:
        secao, _ = obter_secao_passo(texto)
        if secao:
            secao_atual = secao
        passo = normalizar_passo(texto)
        if not passo:
            continue
        fragmentos = FIM_FRASE.split(passo)
        partes: list[str] = []
        for frag in fragmentos:
            frag = compacto(frag)
            if partes and ABREVIATURAS.search(partes[-1]):
                partes[-1] += " " + frag
            else:
                partes.append(frag)
        saida.extend((secao_atual, p) for p in partes if p)
    return saida


def dividir_preparacao(textos: list[str]) -> list[str]:
    """Compatibilidade: devolve apenas o texto limpo de cada passo."""
    return [texto for _, texto in dividir_preparacao_com_seccoes(textos)]


def dividir_ingredientes_com_seccoes(
    textos: list[str], secoes_preparacao: set[str] | None = None
) -> list[tuple[str | None, str]]:
    """Separa listas coladas apenas quando o subtítulo coincide com a preparação."""
    secoes = {compacto(x).casefold() for x in (secoes_preparacao or set())}
    saida: list[tuple[str | None, str]] = []
    secao_atual: str | None = None
    for texto in textos:
        original = compacto(texto)
        primeira, separador, resto = original.partition("-")
        # Evitar dividir hífenes de palavras normais: só reconhecemos um título
        # cujo nome também apareça como subtítulo da preparação desta receita.
        if separador and primeira.strip().casefold() in secoes and resto.startswith(" "):
            secao_atual = primeira.strip()
            parcelas = SEPARADOR_INGREDIENTES.split(resto.strip())
        else:
            parcelas = [original]
        for parcela in parcelas:
            item = normalizar_ingrediente(parcela)
            if item:
                saida.append((secao_atual, item))
    return saida


def normalizar_extras(texto: object) -> str:
    return compacto(texto)


def alertas_qualidade(ingredientes: list[str], preparacao: list[str]) -> list[tuple[str, str]]:
    """Alertas explícitos para revisão; não constituem avaliação de segurança completa."""
    avisos: list[tuple[str, str]] = []
    if len(ingredientes) < 2 or not preparacao:
        avisos.append(("CAMPOS_INCOMPLETOS", "Faltam ingredientes ou preparação estruturados."))
    if any(compacto(i).casefold().strip(":") in CABEÇALHOS_INGREDIENTES for i in ingredientes):
        avisos.append(("CABECALHO_INGREDIENTE", "Há um subtítulo dentro da lista de ingredientes; rever a separação."))
    if any(re.search(r"[-–—]\s+(?=\d|[½¼¾])", i) for i in ingredientes):
        avisos.append(("INGREDIENTES_CONCATENADOS", "Há ingredientes possivelmente unidos numa linha; rever."))
    if any(len(p) > 500 for p in preparacao):
        avisos.append(("PASSO_LONGO", "Há passos longos; verificar se incluem várias operações."))
    if any(MARCADORES_INTERIORES.search(p) for p in preparacao):
        avisos.append(("NUMERACAO_INTERIOR", "Há outra numeração dentro de um passo; rever divisão de etapas."))
    if RISCO_BRASAS.search(" ".join(preparacao)):
        avisos.append(("REVER_CARVAO_EM_BRASA", "Receita com carvão em brasa: requer revisão de segurança antes do treino."))
    return avisos