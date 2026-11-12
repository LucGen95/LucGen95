"""Observador: a parte que roda junto com o jogo.

Num atalho, captura a tela e deixa um pedido pro Claude (a sessão do Claude
Code aberta nesta pasta). Quando ele responde, mostra a decisão num cantinho
da tela. Quem aperta os botões do jogo é você.

Uso:
    python observador.py                 # modo normal, com atalhos e overlay
    python observador.py --teste x.png   # manda uma imagem salva, sem o jogo
"""

from __future__ import annotations

import argparse
import queue
import threading
import time
from pathlib import Path

from PIL import Image

import nucleo

# --------------------------------------------------------------------------
# Configuração (mude à vontade)
# --------------------------------------------------------------------------

ATALHO_ASSISTIR = "<f7>"           # liga/desliga a captura automática
ATALHO_DECIDIR = "<f8>"            # cenas da Kara e do Markus
ATALHO_COMENTAR = "<f9>"           # cenas do Connor
ATALHO_ESCONDER = "<f10>"          # mostra/esconde o overlay
ATALHO_SAIR = "<ctrl>+<shift>+<f10>"

MONITOR = 1                        # 1 = monitor principal
INTERVALO_ASSISTIR = 30            # segundos entre capturas automáticas
LIMITE_RESPOSTA = 180              # segundos esperando o Claude antes de desistir
PASTA = Path(__file__).resolve().parent


def capturar_tela() -> Image.Image:
    import mss

    with mss.mss() as sct:
        bruto = sct.grab(sct.monitors[MONITOR])
    return Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")


# --------------------------------------------------------------------------
# Modo teste: uma imagem salva, sem atalhos nem overlay
# --------------------------------------------------------------------------

def rodar_teste(caminho: str, modo: str) -> None:
    pedido = nucleo.criar_pedido(PASTA, Image.open(caminho), modo)
    print(f"Pedido {pedido['id']} criado. Esperando o Claude responder...")
    if not nucleo.claude_ouvindo(PASTA):
        print("(o Claude não parece estar ouvindo: abra o Claude Code nesta "
              "pasta e peça pra ele começar a jogar)")
    fim = time.monotonic() + LIMITE_RESPOSTA
    while time.monotonic() < fim:
        resposta = nucleo.ler_resposta(PASTA, pedido["id"])
        if resposta:
            print("\n" + nucleo.formatar_para_tela(resposta))
            return
        time.sleep(0.3)
    nucleo.cancelar_pedido(PASTA)
    print("O Claude não respondeu a tempo. Pedido cancelado.")


# --------------------------------------------------------------------------
# Modo normal
# --------------------------------------------------------------------------

class Observador:
    def __init__(self) -> None:
        import tkinter as tk

        self.fila: queue.Queue[tuple[str, object]] = queue.Queue()
        self.ocupado = threading.Lock()   # preso enquanto há pedido sem resposta
        self.pendente: dict | None = None  # só a thread do tkinter mexe
        self.assistindo = False
        self.ultima_enviada: Image.Image | None = None
        self.pedidos = 0
        nucleo.cancelar_pedido(PASTA)      # sobra de uma sessão anterior

        self.raiz = tk.Tk()
        self.raiz.overrideredirect(True)            # sem borda nem barra de título
        self.raiz.attributes("-topmost", True)      # fica por cima do jogo
        self.raiz.attributes("-alpha", 0.88)
        self.raiz.configure(bg="#101418")
        self.raiz.geometry("+24+24")                # canto superior esquerdo
        self.rotulo = tk.Label(
            self.raiz,
            text="",
            font=("Segoe UI", 13),
            fg="#e8f0f7",
            bg="#101418",
            justify="left",
            anchor="w",
            wraplength=460,
            padx=14,
            pady=10,
        )
        self.rotulo.pack()
        self.visivel = True
        self.mostrar(
            "Observador pronto.\n"
            "F8 decide | F9 comenta | F7 assistir | F10 esconde | Ctrl+Shift+F10 sai"
        )
        self.raiz.after(100, self._ciclo)
        self.raiz.after(INTERVALO_ASSISTIR * 1000, self._captura_automatica)

    # ---- overlay (só a thread do tkinter mexe na janela) ----

    def mostrar(self, texto: str) -> None:
        self.rotulo.configure(text=texto)

    def _ciclo(self) -> None:
        try:
            while True:
                acao, valor = self.fila.get_nowait()
                if acao == "sair":
                    self.raiz.destroy()
                    return
                if acao == "alternar":
                    self.visivel = not self.visivel
                    if self.visivel:
                        self.raiz.deiconify()
                    else:
                        self.raiz.withdraw()
                elif acao == "assistir":
                    self.assistindo = not self.assistindo
                    self.mostrar(
                        f"Assistir ligado: mando uma captura a cada {INTERVALO_ASSISTIR}s."
                        if self.assistindo else "Assistir desligado."
                    )
                elif acao == "pedido":
                    self.pendente = valor
                else:
                    self.mostrar(str(valor))
        except queue.Empty:
            pass
        self._conferir_resposta()
        self.raiz.after(100, self._ciclo)

    def _conferir_resposta(self) -> None:
        if self.pendente is None:
            return
        pedido = self.pendente
        resposta = nucleo.ler_resposta(PASTA, pedido["id"])
        if resposta is not None:
            calado = pedido["modo"] == nucleo.MODO_ASSISTIR and resposta["tipo"] == "sem_decisao"
            if not calado:
                texto = nucleo.formatar_para_tela(resposta)
                self.mostrar(texto)
                print(f"\n[{resposta['tipo']}] {resposta['situacao']}\n{texto}")
        elif time.monotonic() - pedido["desde"] > LIMITE_RESPOSTA:
            nucleo.cancelar_pedido(PASTA)
            if pedido["modo"] != nucleo.MODO_ASSISTIR:
                self.mostrar(
                    "O Claude não respondeu. Confere se o Claude Code está "
                    "aberto na pasta do projeto e jogando."
                )
        else:
            return
        self.pendente = None
        self.ocupado.release()

    def _captura_automatica(self) -> None:
        if self.assistindo:
            threading.Thread(
                target=self.ao_apertar, args=(nucleo.MODO_ASSISTIR,), daemon=True
            ).start()
        self.raiz.after(INTERVALO_ASSISTIR * 1000, self._captura_automatica)

    # ---- atalhos (rodam fora da thread do tkinter) ----

    def ao_apertar(self, modo: str) -> None:
        # Captura na hora do aperto, antes de qualquer espera, pra pegar a
        # tela certa mesmo que você pause o jogo logo depois.
        if not self.ocupado.acquire(blocking=False):
            return  # o Claude ainda está pensando na captura anterior
        automatica = modo == nucleo.MODO_ASSISTIR
        try:
            img = capturar_tela()
            if nucleo.parece_tela_preta(img):
                raise RuntimeError(
                    "a captura saiu preta. Coloca o jogo em janela sem bordas "
                    "nas opções de vídeo e tenta de novo."
                )
            if automatica and not nucleo.mudou_bastante(self.ultima_enviada, img):
                self.ocupado.release()
                return  # tela parada: não gasta uma captura à toa
            pedido = nucleo.criar_pedido(PASTA, img, modo)
        except Exception as erro:  # noqa: BLE001
            self.ocupado.release()
            if not automatica:
                self.fila.put(("texto", f"Não deu pra capturar: {erro}"))
            print(f"ERRO: {erro!r}")
            return
        self.ultima_enviada = img
        self.pedidos += 1
        pedido["desde"] = time.monotonic()
        self.fila.put(("pedido", pedido))
        if not automatica:
            aviso = "" if nucleo.claude_ouvindo(PASTA) else (
                "\n(o Claude não parece estar ouvindo: ele está jogando no Claude Code?)"
            )
            self.fila.put(("texto", "Pensando..." + aviso))

    def rodar(self) -> None:
        from pynput import keyboard

        atalhos = keyboard.GlobalHotKeys(
            {
                ATALHO_DECIDIR: lambda: self.ao_apertar(nucleo.MODO_DECIDIR),
                ATALHO_COMENTAR: lambda: self.ao_apertar(nucleo.MODO_COMENTAR),
                ATALHO_ASSISTIR: lambda: self.fila.put(("assistir", None)),
                ATALHO_ESCONDER: lambda: self.fila.put(("alternar", None)),
                ATALHO_SAIR: lambda: self.fila.put(("sair", None)),
            }
        )
        atalhos.start()
        try:
            self.raiz.mainloop()
        finally:
            atalhos.stop()
            nucleo.cancelar_pedido(PASTA)
            print(f"\nFim. {self.pedidos} capturas enviadas nesta sessão.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude observando Detroit: Become Human")
    parser.add_argument("--teste", metavar="IMAGEM", help="manda uma imagem salva pro Claude")
    parser.add_argument(
        "--modo",
        choices=nucleo.MODOS,
        default=nucleo.MODO_DECIDIR,
        help="modo usado com --teste",
    )
    args = parser.parse_args()
    if args.teste:
        rodar_teste(args.teste, args.modo)
    else:
        Observador().rodar()


if __name__ == "__main__":
    main()
