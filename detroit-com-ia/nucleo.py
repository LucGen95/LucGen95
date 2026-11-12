"""Núcleo do observador: preparo da imagem, fila de pedidos e diário.

Não existe mais chamada de API aqui. Quem joga é a sessão do Claude Code
aberta nesta pasta (pela assinatura): o observador deixa um pedido na pasta
`fila/`, o Claude lê a captura e responde com `jogar.py`.

Nada aqui depende de Windows, teclado ou tela, então dá pra testar em
qualquer máquina (veja teste_nucleo.py).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

LARGURA_MAX = 1280         # a captura é reduzida pra essa largura antes de salvar
QUALIDADE_JPEG = 85
DECISOES_NO_RESUMO = 40    # quantas entradas recentes do diário entram no resumo
CAPTURAS_GUARDADAS = 60    # imagens antigas além disso são apagadas
LARGURA_LEGENDA = 960      # largura de cada recorte de legenda
FAIXA_LEGENDA = (0.72, 0.97)  # onde ficam as legendas: de 72% a 97% da altura
TOLERANCIA_OUVINDO = 60    # segundos sem sinal até achar que o Claude saiu

MODO_DECIDIR = "decidir"     # cenas da Kara e do Markus: o Claude manda
MODO_COMENTAR = "comentar"   # cenas do Connor: o Lucas joga, o Claude diz o que faria
MODO_ASSISTIR = "assistir"   # captura automática: o Claude comenta só se quiser
MODOS = (MODO_DECIDIR, MODO_COMENTAR, MODO_ASSISTIR)

TIPOS = ("escolha", "exploracao", "qte", "sem_decisao", "comentario")
LEITURAS = ("alta", "media", "baixa")
CAMPOS = ("situacao", "tipo", "decisao", "botao", "motivo", "leitura")

EXPLICACAO_DO_MODO = {
    MODO_DECIDIR: "a decisão desta tela é sua",
    MODO_COMENTAR: "o Lucas está no controle; diga o que você faria, sem mandar",
    MODO_ASSISTIR: "captura automática; comente só se tiver algo a dizer, "
                   "senão responda com --tipo sem_decisao",
}


# --------------------------------------------------------------------------
# Imagem
# --------------------------------------------------------------------------

def preparar_imagem(img: Image.Image, largura_max: int = LARGURA_MAX) -> Image.Image:
    """Converte pra RGB e reduz a captura (nunca amplia)."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > largura_max:
        altura = round(img.height * largura_max / img.width)
        img = img.resize((largura_max, altura), Image.LANCZOS)
    return img


def parece_tela_preta(img: Image.Image) -> bool:
    """Detecta captura quase toda preta (comum em tela cheia exclusiva)."""
    pequena = img.convert("L").resize((64, 36))
    return max(pequena.getdata()) < 12


def mudou_bastante(antes: Image.Image | None, agora: Image.Image, limiar: float = 6.0) -> bool:
    """Diz se a tela mudou o suficiente pra valer uma nova captura automática."""
    if antes is None:
        return True
    a = antes.convert("L").resize((64, 36))
    b = agora.convert("L").resize((64, 36))
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0] > limiar


def recortar_legenda(img: Image.Image) -> Image.Image:
    """Recorta a faixa de baixo da tela, onde o jogo mostra as legendas."""
    topo, base = (round(img.height * f) for f in FAIXA_LEGENDA)
    faixa = img.crop((0, topo, img.width, base)).convert("RGB")
    if faixa.width > LARGURA_LEGENDA:
        altura = max(1, round(faixa.height * LARGURA_LEGENDA / faixa.width))
        faixa = faixa.resize((LARGURA_LEGENDA, altura), Image.LANCZOS)
    return faixa


def montar_tira(recortes: list[Image.Image]) -> Image.Image | None:
    """Empilha os recortes de legenda (mais antigo em cima) numa imagem só."""
    if not recortes:
        return None
    borda = 3
    largura = max(r.width for r in recortes)
    altura = sum(r.height for r in recortes) + borda * (len(recortes) - 1)
    tira = Image.new("RGB", (largura, altura), (255, 0, 255))
    y = 0
    for recorte in recortes:
        tira.paste(recorte, (0, y))
        y += recorte.height + borda
    return tira


# --------------------------------------------------------------------------
# Diário (memória entre sessões e depois que o contexto é resumido)
# --------------------------------------------------------------------------

def carregar_diario(caminho: Path, ultimas: int = DECISOES_NO_RESUMO) -> list[dict]:
    if not caminho.exists():
        return []
    entradas = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            entradas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue  # linha corrompida não derruba o jogo
    return entradas[-ultimas:]


def registrar_no_diario(caminho: Path, decisao: dict, modo: str) -> None:
    entrada = {"quando": time.strftime("%Y-%m-%d %H:%M:%S"), "modo": modo}
    entrada.update({c: decisao.get(c, "") for c in CAMPOS})
    with caminho.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")


def resumir_diario(entradas: list[dict]) -> str:
    # telas sem nada pra decidir não ajudam a lembrar da história
    uteis = [e for e in entradas if e.get("tipo") not in ("sem_decisao", "qte")]
    if not uteis:
        return "Ainda não há decisões registradas. Este é o começo."
    linhas = []
    for e in uteis:
        quem = "você decidiu" if e.get("modo") == MODO_DECIDIR else "Lucas no controle"
        linhas.append(f"- [{quem}] {e.get('situacao', '')} -> {e.get('decisao', '')}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# Fila de pedidos (a ponte entre o observador e o Claude Code)
#
#   fila/pedido.json     o observador escreve: {id, modo, imagem, quando}
#                        e, se houver, legendas (tira com as falas recentes)
#   fila/resposta.json   o Claude escreve (via jogar.py): {id, ...CAMPOS}
#   fila/ouvindo         o jogar.py toca enquanto espera; o observador usa
#                        pra avisar quando não tem ninguém do outro lado
#
# Só existe um pedido por vez. Ele está pendente enquanto a resposta não
# tiver o mesmo id.
# --------------------------------------------------------------------------

def _escrever_json(caminho: Path, dado: dict) -> None:
    """Escrita atômica: o outro lado nunca lê um arquivo pela metade."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, caminho)


def _ler_json(caminho: Path) -> dict | None:
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dado if isinstance(dado, dict) else None


def criar_pedido(pasta: Path, img: Image.Image, modo: str,
                 legendas: list[Image.Image] | None = None) -> dict:
    """Salva a captura (e a tira de legendas) e deixa o pedido pro Claude."""
    capturas = pasta / "capturas"
    capturas.mkdir(parents=True, exist_ok=True)
    ident = str(int(time.time() * 1000))
    imagem = capturas / f"{ident}.jpg"
    preparar_imagem(img).save(imagem, format="JPEG", quality=QUALIDADE_JPEG)
    pedido = {
        "id": ident,
        "modo": modo,
        "imagem": str(imagem.resolve()),
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tira = montar_tira(legendas or [])
    if tira is not None:
        caminho_tira = capturas / f"{ident}-legendas.jpg"
        tira.save(caminho_tira, format="JPEG", quality=QUALIDADE_JPEG)
        pedido["legendas"] = str(caminho_tira.resolve())
    for velha in sorted(capturas.glob("*.jpg"))[:-CAPTURAS_GUARDADAS]:
        velha.unlink(missing_ok=True)
    _escrever_json(pasta / "fila" / "pedido.json", pedido)
    return pedido


def cancelar_pedido(pasta: Path) -> None:
    (pasta / "fila" / "pedido.json").unlink(missing_ok=True)


def pedido_pendente(pasta: Path) -> dict | None:
    pedido = _ler_json(pasta / "fila" / "pedido.json")
    if not pedido or "id" not in pedido:
        return None
    resposta = _ler_json(pasta / "fila" / "resposta.json")
    if resposta and resposta.get("id") == pedido["id"]:
        return None
    return pedido


def esperar_pedido(pasta: Path, limite_s: float, intervalo: float = 0.3,
                   dormir=time.sleep, relogio=time.monotonic) -> dict | None:
    """Bloqueia até aparecer um pedido pendente ou o limite estourar."""
    sinal = pasta / "fila" / "ouvindo"
    sinal.parent.mkdir(parents=True, exist_ok=True)
    fim = relogio() + limite_s
    while True:
        sinal.write_text(str(time.time()), encoding="ascii")
        pedido = pedido_pendente(pasta)
        if pedido is not None:
            return pedido
        if relogio() >= fim:
            return None
        dormir(intervalo)


def claude_ouvindo(pasta: Path, tolerancia: float = TOLERANCIA_OUVINDO) -> bool:
    try:
        return time.time() - (pasta / "fila" / "ouvindo").stat().st_mtime < tolerancia
    except OSError:
        return False


def validar_decisao(dado: dict) -> dict:
    """Devolve a decisão só com os CAMPOS, ou levanta ValueError."""
    decisao = {c: str(dado.get(c) or "").strip() for c in CAMPOS}
    decisao["leitura"] = decisao["leitura"] or "alta"
    if decisao["tipo"] not in TIPOS:
        raise ValueError(f"tipo inválido: {decisao['tipo']!r}. Use um de: {', '.join(TIPOS)}")
    if decisao["leitura"] not in LEITURAS:
        raise ValueError(f"leitura inválida: {decisao['leitura']!r}. Use um de: {', '.join(LEITURAS)}")
    if decisao["tipo"] in ("escolha", "exploracao", "comentario") and not decisao["decisao"]:
        raise ValueError(f"o tipo {decisao['tipo']!r} precisa de --decisao")
    return decisao


def responder(pasta: Path, diario: Path, dado: dict) -> dict:
    """Responde o pedido pendente: grava no diário e avisa o observador."""
    decisao = validar_decisao(dado)
    pedido = pedido_pendente(pasta)
    if pedido is None:
        raise ValueError(
            "não há pedido pendente (o Lucas pode ter cancelado ou o tempo "
            "estourou). Nada foi registrado."
        )
    registrar_no_diario(diario, decisao, pedido.get("modo", MODO_DECIDIR))
    _escrever_json(pasta / "fila" / "resposta.json", {"id": pedido["id"], **decisao})
    return decisao


def ler_resposta(pasta: Path, ident: str) -> dict | None:
    resposta = _ler_json(pasta / "fila" / "resposta.json")
    if resposta and resposta.get("id") == ident:
        return {c: str(resposta.get(c, "")) for c in CAMPOS}
    return None


# --------------------------------------------------------------------------
# Texto pro overlay
# --------------------------------------------------------------------------

def formatar_para_tela(decisao: dict) -> str:
    tipo = decisao["tipo"]
    if tipo == "qte":
        cabeca = "QTE: é com você!"
    elif tipo == "sem_decisao":
        cabeca = "Nada pra decidir aqui."
    elif tipo == "comentario":
        cabeca = f"Claude: {decisao['decisao']}"
    else:
        botao = f"  [{decisao['botao']}]" if decisao["botao"] else ""
        cabeca = f">> {decisao['decisao']}{botao}"
    partes = [cabeca]
    if decisao["motivo"]:
        partes.append(decisao["motivo"])
    if decisao["leitura"] == "baixa":
        partes.append("(não li a tela direito, confere aí)")
    return "\n".join(partes)
