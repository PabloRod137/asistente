"""
Coincidencia de nombres contra la lista de clientes reales importados sin teléfono
(clientes_importados_pendientes, Fase 9.1).

Cuando alguien nuevo escribe a Maira y da su nombre, se compara contra esa lista para ver si
ya es un cliente conocido de LexGuardian al que simplemente le falta enlazar su número de
WhatsApp. La comparación es deliberadamente conservadora: si hay ambigüedad, no propone nada
(mejor preguntar de más que asignar mal el expediente o el NIF de otra persona). Además, quien
llame a este módulo SIEMPRE debe pedir confirmación explícita al cliente antes de fusionar
datos — esta función solo sugiere candidatos, nunca decide por sí sola.
"""
import re
import unicodedata

import database


def _tokens(texto: str) -> set:
    if not texto:
        return set()
    s = texto.upper()
    s = "".join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z\s]', ' ', s)
    return {t for t in s.split() if len(t) > 1}


def buscar_coincidencia(nombre_escrito: str) -> dict | None:
    """
    Busca en la lista de espera un cliente cuyo nombre completo contenga TODAS las palabras
    que la persona acaba de escribir. Devuelve el candidato (dict de clientes_importados_pendientes)
    si hay una única coincidencia clara, o None si no hay ninguna o si hay ambigüedad.
    """
    tokens_entrada = _tokens(nombre_escrito)
    if len(tokens_entrada) < 2:
        # Un solo token (ej. solo un nombre de pila) es demasiado ambiguo para buscar.
        return None

    pendientes = database.listar_clientes_pendientes(solo_no_promovidos=True)
    candidatos = []
    for p in pendientes:
        tokens_candidato = _tokens(p["nombre"])
        if not tokens_candidato:
            continue
        if tokens_entrada.issubset(tokens_candidato):
            union = tokens_entrada | tokens_candidato
            score = len(tokens_entrada) / len(union)
            candidatos.append((score, p))

    if not candidatos:
        return None

    candidatos.sort(key=lambda x: x[0], reverse=True)
    mejor_score = candidatos[0][0]
    empatados = [p for score, p in candidatos if score == mejor_score]

    if len(empatados) > 1:
        return None

    return empatados[0]
