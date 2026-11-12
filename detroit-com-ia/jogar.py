"""Comandos que o Claude (sessão do Claude Code nesta pasta) usa pra jogar.

    python jogar.py diario      # resumo do que já aconteceu
    python jogar.py esperar     # bloqueia até o Lucas mandar uma captura
    python jogar.py responder --tipo escolha --decisao "..." --botao X --motivo "..."
                                # responde e já fica esperando a próxima

Cada comando bloqueia por no máximo LIMITE_PADRAO segundos, pra caber no
tempo de um comando do Claude Code. Se der "SEM PEDIDO", é só rodar de novo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nucleo

PASTA = Path(__file__).resolve().parent
DIARIO = PASTA / "diario.jsonl"
LIMITE_PADRAO = 540  # segundos; abaixo do teto de 10 minutos por comando


def esperar(limite: float) -> None:
    pedido = nucleo.esperar_pedido(PASTA, limite)
    if pedido is None:
        print(f"SEM PEDIDO em {limite:.0f}s. Rode `python jogar.py esperar` de novo.")
        return
    modo = pedido.get("modo", nucleo.MODO_DECIDIR)
    print(f"PEDIDO {pedido['id']}")
    print(f"modo: {modo} ({nucleo.EXPLICACAO_DO_MODO.get(modo, '')})")
    print(f"imagem: {pedido['imagem']}")
    if pedido.get("legendas"):
        print(f"legendas: {pedido['legendas']}")
        print("  (faixa de baixo da tela a cada 2s desde a última captura, da "
              "mais antiga em cima pra mais recente embaixo; leia antes da imagem)")
    print("Leia as imagens e responda com `python jogar.py responder ...`.")


def main() -> None:
    for saida in (sys.stdout, sys.stderr):
        saida.reconfigure(encoding="utf-8")  # acentos no terminal do Windows

    parser = argparse.ArgumentParser(description="Comandos do Claude pra jogar Detroit")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("diario", help="mostra o resumo das decisões anteriores")

    p_esperar = sub.add_parser("esperar", help="espera a próxima captura")
    p_esperar.add_argument("--limite", type=float, default=LIMITE_PADRAO)

    p_resp = sub.add_parser("responder", help="responde a captura e espera a próxima")
    p_resp.add_argument("--tipo", required=True, choices=nucleo.TIPOS)
    p_resp.add_argument("--decisao", default="", help="opção escolhida, próximo passo ou comentário")
    p_resp.add_argument("--botao", default="", help="botão da opção, como aparece na tela")
    p_resp.add_argument("--motivo", default="", help="por quê, em 1 a 3 frases curtas")
    p_resp.add_argument("--situacao", default="", help="uma frase: quem está em cena e o que acontece")
    p_resp.add_argument("--leitura", default="alta", choices=nucleo.LEITURAS)
    p_resp.add_argument("--parar", action="store_true", help="não esperar a próxima captura")
    p_resp.add_argument("--limite", type=float, default=LIMITE_PADRAO)

    args = parser.parse_args()

    if args.comando == "diario":
        print(nucleo.resumir_diario(nucleo.carregar_diario(DIARIO)))
    elif args.comando == "esperar":
        esperar(args.limite)
    else:
        try:
            decisao = nucleo.responder(PASTA, DIARIO, vars(args))
            print("Registrado e enviado pro overlay:")
            print(nucleo.formatar_para_tela(decisao))
        except ValueError as erro:
            print(f"NÃO REGISTRADO: {erro}")
        if not args.parar:
            print()
            esperar(args.limite)


if __name__ == "__main__":
    main()
