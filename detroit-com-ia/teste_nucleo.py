"""Testes do núcleo (não precisa do jogo nem do Claude, roda em qualquer SO).

    python teste_nucleo.py
"""

import os
import tempfile
import time
from pathlib import Path

from PIL import Image

import nucleo

DECISAO = {
    "situacao": "Kara na cozinha com o Todd gritando",
    "tipo": "escolha",
    "decisao": "PROTEGER ALICE",
    "botao": "X",
    "motivo": "Ela é uma criança e ninguém mais vai fazer isso.",
    "leitura": "alta",
}


def tela(cor=(90, 120, 150), tamanho=(2560, 1440)):
    return Image.new("RGB", tamanho, cor)


def teste_imagem():
    assert nucleo.preparar_imagem(tela()).size == (1280, 720)
    # imagem pequena não é ampliada; RGBA vira RGB
    pequena = nucleo.preparar_imagem(Image.new("RGBA", (800, 600)))
    assert pequena.size == (800, 600) and pequena.mode == "RGB"
    assert nucleo.parece_tela_preta(tela((0, 0, 0)))
    assert not nucleo.parece_tela_preta(tela())
    assert nucleo.mudou_bastante(None, tela())
    assert not nucleo.mudou_bastante(tela(), tela((91, 121, 151)))
    assert nucleo.mudou_bastante(tela(), tela((200, 40, 40)))


def teste_diario():
    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "diario.jsonl"
        assert nucleo.carregar_diario(caminho) == []
        nucleo.registrar_no_diario(caminho, DECISAO, nucleo.MODO_DECIDIR)
        comentario = dict(DECISAO, tipo="comentario", situacao="Connor no telhado",
                          decisao="Falar a verdade pro Daniel")
        nucleo.registrar_no_diario(caminho, comentario, nucleo.MODO_COMENTAR)
        nucleo.registrar_no_diario(caminho, dict(DECISAO, tipo="qte"), nucleo.MODO_DECIDIR)
        with caminho.open("a", encoding="utf-8") as f:
            f.write("linha quebrada {\n")
        entradas = nucleo.carregar_diario(caminho)
        assert len(entradas) == 3
        resumo = nucleo.resumir_diario(entradas)
        assert "você decidiu" in resumo and "PROTEGER ALICE" in resumo
        assert "Lucas no controle" in resumo and "Daniel" in resumo
        assert resumo.count("\n") == 1  # o QTE fica de fora
        assert len(nucleo.carregar_diario(caminho, ultimas=1)) == 1
        assert "começo" in nucleo.resumir_diario([])


def teste_fila_ida_e_volta():
    with tempfile.TemporaryDirectory() as nome:
        pasta = Path(nome)
        diario = pasta / "diario.jsonl"
        assert nucleo.pedido_pendente(pasta) is None
        assert nucleo.esperar_pedido(pasta, limite_s=0) is None
        assert nucleo.claude_ouvindo(pasta)  # esperar deixou o sinal

        pedido = nucleo.criar_pedido(pasta, tela(), nucleo.MODO_COMENTAR)
        assert Image.open(pedido["imagem"]).size == (1280, 720)
        assert Path(pedido["imagem"]).is_absolute()
        assert nucleo.esperar_pedido(pasta, limite_s=0) == pedido
        assert nucleo.ler_resposta(pasta, pedido["id"]) is None

        decisao = nucleo.responder(pasta, diario, dict(DECISAO, extra="ignorado"))
        assert decisao == DECISAO
        assert nucleo.ler_resposta(pasta, pedido["id"]) == DECISAO
        assert nucleo.ler_resposta(pasta, "outro-id") is None
        assert nucleo.pedido_pendente(pasta) is None  # respondido não volta
        entrada = nucleo.carregar_diario(diario)[0]
        assert entrada["modo"] == nucleo.MODO_COMENTAR and entrada["decisao"] == "PROTEGER ALICE"


def teste_fila_casos_ruins():
    with tempfile.TemporaryDirectory() as nome:
        pasta = Path(nome)
        diario = pasta / "diario.jsonl"

        def falha(dado):
            try:
                nucleo.responder(pasta, diario, dado)
            except ValueError as erro:
                return str(erro)
            raise AssertionError("devia ter falhado")

        assert "pendente" in falha(DECISAO)  # sem pedido
        nucleo.criar_pedido(pasta, tela(), nucleo.MODO_DECIDIR)
        assert "tipo" in falha(dict(DECISAO, tipo="chute"))
        assert "leitura" in falha(dict(DECISAO, leitura="otima"))
        assert "--decisao" in falha(dict(DECISAO, decisao=""))
        assert not diario.exists()  # resposta inválida não suja o diário
        # sem_decisao não precisa de decisão; leitura vazia vira "alta"
        ok = nucleo.responder(pasta, diario, {"tipo": "sem_decisao", "decisao": None})
        assert ok["leitura"] == "alta" and ok["decisao"] == ""

        # pedido cancelado pelo observador: a resposta atrasada é recusada
        nucleo.criar_pedido(pasta, tela(), nucleo.MODO_DECIDIR)
        nucleo.cancelar_pedido(pasta)
        assert "pendente" in falha(DECISAO)
        nucleo.cancelar_pedido(pasta)  # cancelar duas vezes não dá erro

        # arquivo pela metade é tratado como ausente
        (pasta / "fila" / "pedido.json").write_text('{"id": "1', encoding="utf-8")
        assert nucleo.pedido_pendente(pasta) is None

        # sinal velho: ninguém ouvindo
        assert not nucleo.claude_ouvindo(pasta)  # nunca esperou
        nucleo.esperar_pedido(pasta, limite_s=0)
        sinal = pasta / "fila" / "ouvindo"
        velho = time.time() - 3600
        os.utime(sinal, (velho, velho))
        assert not nucleo.claude_ouvindo(pasta)


def teste_espera_acorda_com_pedido():
    with tempfile.TemporaryDirectory() as nome:
        pasta = Path(nome)
        voltas = []

        def dormir(_):
            voltas.append(1)
            if len(voltas) == 3:
                nucleo.criar_pedido(pasta, tela(), nucleo.MODO_ASSISTIR)

        pedido = nucleo.esperar_pedido(pasta, limite_s=60, dormir=dormir)
        assert pedido["modo"] == nucleo.MODO_ASSISTIR and len(voltas) == 3


def teste_limpeza_de_capturas():
    with tempfile.TemporaryDirectory() as nome:
        pasta = Path(nome)
        capturas = pasta / "capturas"
        capturas.mkdir()
        for i in range(nucleo.CAPTURAS_GUARDADAS + 5):
            (capturas / f"{i:013d}.jpg").write_bytes(b"x")
        pedido = nucleo.criar_pedido(pasta, tela(), nucleo.MODO_DECIDIR)
        restantes = sorted(capturas.glob("*.jpg"))
        assert len(restantes) == nucleo.CAPTURAS_GUARDADAS
        assert Path(pedido["imagem"]) in [r.resolve() for r in restantes]


def teste_overlay():
    assert nucleo.formatar_para_tela(DECISAO).startswith(">> PROTEGER ALICE  [X]")
    assert "QTE" in nucleo.formatar_para_tela(dict(DECISAO, tipo="qte"))
    baixa = nucleo.formatar_para_tela(dict(DECISAO, leitura="baixa"))
    assert "confere" in baixa
    assert nucleo.formatar_para_tela(dict(DECISAO, tipo="comentario")).startswith("Claude: ")


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
    for t in testes:
        t()
        print("ok ", t.__name__)
    print(f"\n{len(testes)} testes passaram.")
