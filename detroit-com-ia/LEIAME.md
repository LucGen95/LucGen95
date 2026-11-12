# Detroit com IA

Você joga Detroit: Become Human; num atalho, o script captura a tela e manda
pro Claude, que responde num cantinho da tela. Quem aperta os botões é você.

Quem decide é a sessão do Claude Code aberta nesta pasta, pela sua
assinatura. Não usa API nem chave.

## Instalação (Windows)

1. Python 3.10 ou mais novo.
2. Na pasta do projeto:
   ```
   pip install -r requirements.txt
   ```
3. Claude Code instalado e logado com a conta da assinatura.

**Importante:** não deixe a variável `ANTHROPIC_API_KEY` definida. Com ela, o
Claude Code cobra da API em vez de usar o plano. Se você chegou a criar essa
variável, apague.

## Primeiro teste (sem o jogo)

1. Abra o Claude Code nesta pasta e diga: **bora jogar**. Ele fica esperando.
   Na primeira vez ele pede permissão pra rodar `python jogar.py`; escolha a
   opção de permitir sempre, senão ele para a cada captura.
2. Em outro terminal, com um print de qualquer cena do jogo:
   ```
   python observador.py --teste print.png
   ```

Se a decisão aparecer nesse terminal, a ponte está funcionando.

## Jogando

1. Nas opções de vídeo do jogo, use **janela sem bordas**. Em tela cheia
   exclusiva a captura sai preta e o overlay não aparece.
2. Deixe o Claude Code aberto na pasta, jogando ("bora jogar").
3. Rode `python observador.py` e deixe o terminal aberto.
4. Atalhos:

   | Tecla | O que faz |
   | --- | --- |
   | F8 | Cena da Kara ou do Markus: o Claude decide |
   | F9 | Cena do Connor: o Claude diz o que faria |
   | F7 | Liga/desliga o modo assistir: uma captura a cada 30s, e o Claude comenta se quiser |
   | F10 | Mostra/esconde o overlay |
   | Ctrl+Shift+F10 | Sai |

5. Quando aparecer uma escolha, aperte F8. A captura é feita na hora do
   aperto, então dá pra pausar o jogo logo em seguida enquanto ele pensa
   (teste se o pause segura o cronômetro das escolhas).
6. Aperte F9 de vez em quando nas cenas do Connor. Isso entra no diário e o
   Claude fica sabendo o que aconteceu na sua parte da história.

Cada captura gasta do limite de uso do seu plano. O modo assistir é o que
mais gasta; ligue só nas cenas em que quiser comentário.

## Arquivos

- `observador.py`: atalhos, captura de tela e overlay.
- `jogar.py`: os comandos que o Claude usa pra esperar e responder.
- `nucleo.py`: fila de pedidos, preparo da imagem e diário.
- `teste_nucleo.py`: testes do núcleo (`python teste_nucleo.py`).
- `CLAUDE.md`: as regras do jogo e as instruções que o Claude segue.
- `diario.jsonl` (criado ao jogar): todas as decisões. É a memória do Claude
  entre sessões. Apagar o arquivo zera a memória.
- `capturas/` (criado ao jogar): as últimas 50 telas enviadas, pra conferir
  o que ele viu quando a decisão parecer estranha.

## O que foi e o que não foi testado

Testado (em Linux): os testes do núcleo e uma rodada completa de pedido e
resposta com `--teste`.

Ainda não testado: o overlay e os atalhos no Windows, e tudo com o jogo
aberto. Se os atalhos não responderem com o jogo em foco, tente rodar o
terminal como administrador.
