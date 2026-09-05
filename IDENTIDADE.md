# NÓRIA — Identidade visual e abertura

Referência: `web/img/noria-logo-ref.jpeg` — cérebro cromado, núcleo ciano, seis nós
satélites ligados por trilhas luminosas, tipografia em metal escovado sobre grafite
quase preto. A identidade traduz isso para interface: superfície escura e neutra,
metal nas bordas, **um** ponto de luz (o núcleo) e nada mais brilhando.

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `web/css/tokens.css` | sistema de design completo em CSS custom properties |
| `web/js/abertura.js` | módulo ES da sequência de inicialização em `<canvas>` |
| `web/abertura-teste.html` | página autônoma para testar a abertura em tela cheia |

## Paleta

Superfícies em quatro degraus de grafite (`--painel-fundo` #0B0E12 → `--fundo` #101318
→ `--painel` #191E26 → `--painel-alto` #222936), de modo que elevação seja lida sem
sombra forte. Texto em quatro pesos de tinta (#F3F5F7 → #ADB7C6 → #6F7B8C → #4A5464):
título, apoio, rótulo, desativado.

O acento é único: `--acento` #50D6BC, verde-água do núcleo do logo. Ele só aparece em
ação principal, estado ativo e no núcleo — nunca como decoração. Semântica separada e
discreta: `--ok` #68D391, `--atencao` #F2C66D, `--erro` #F08080. O metal do logo vive
em `--cromo` #C6CFDA e no gradiente `--cromo-metal`, usado na marca ("NÓRIA" em metal
escovado) e em traços finos. Linhas em três níveis de opacidade da tinta (.08 / .14 /
.22) substituem molduras pesadas.

**Tema claro** (`[data-tema="claro"]`) reescreve os mesmos nomes: fundo #F4F6F9, painel
branco, tinta #141922 e acento escurecido para #0E9C82 — o único desvio de matiz, feito
para o verde-água manter contraste de texto sobre branco. O canvas da abertura detecta
a luminância de `--fundo` e reforça traços e núcleo no claro; a troca de tema é
observada em tempo real (MutationObserver).

## Tipografia e ritmo

- `--display` Cabinet Grotesk 800 — marca e títulos, `letter-spacing` negativo.
- `--corpo` Satoshi — texto de interface, base em `--t-base` 15.5px.
- `--mono` JetBrains Mono — números tabulares, log de sistema, rótulos técnicos.

Escala contida (10.5 → 42px), sem tipo gigante: é um sistema de decisão, não uma landing
page. Espaçamento em múltiplos de 4 (`--e-1`…`--e-24`), raios de 10–12px
(`--raio` 10, `--raio-md` 12) conforme pedido, sombras discretas em quatro degraus e um
único efeito de luz (`--brilho-nucleo`). `@media (prefers-reduced-motion: reduce)`
zera durações e desliga animações.

## Sequência de abertura (~9 s)

Nada de "cérebro de pontos aleatórios". A forma do logo é reconstruída: núcleo central
pulsante e seis nós em órbita elíptica — **dados, processos, investigação, pessoas,
validação, decisão** —, cada um com ícone geométrico (barras, engrenagem, lupa, pessoas,
visto, visto duplo) e trilha curva até o núcleo, por onde correm duas partículas que vão
ao núcleo e voltam. Rótulos em mono minúsculo acendem junto com a trilha.

1. **Isolamento** (0–2,3 s): núcleo nasce, arco de varredura gira uma vez.
   Log: instância isolada — `noria-prod-01`, cofre selado, integridade do banco verificada.
2. **Funções** (2,3–5,9 s): as seis trilhas acendem em sequência alternando lados; o anel
   do nó se completa e o núcleo cresce a cada função ativa.
3. **Fontes autorizadas** (5,9–7,6 s): ATUA somente leitura, extrato OFX, acervo interno.
4. **Operação** (7,6–9 s): "NÚCLEO EM OPERAÇÃO / aguardando objetivo" sob a constelação.

O log ocupa a base em janela rolante de 7 linhas com opacidade decrescente e efeito de
digitação. Canvas responsivo (devicePixelRatio, redesenho em resize, rAF cancelado ao
fim); em telas estreitas a constelação fica mais vertical e o log sobe para não colidir
com o botão. `pular()` salta para o quadro final; com movimento reduzido, desenha o
quadro final estático e conclui em 400 ms.

## Verificação

Capturas em 1500×940 (1 s, 3 s, 5,5 s, 8,5 s), em 390×860 e no tema claro. Ajustes
feitos após olhar as imagens: órbita pontilhada trocada por linha sólida muito fraca
(os pontos pareciam sujeira/texto fantasma), ícone de engrenagem redesenhado (parecia um
sol), geometria mais vertical e log elevado no celular, pisos de opacidade maiores para o
log no tema claro, núcleo em verde-água (em vez de branco) no tema claro e correção do
quadro estático em `prefers-reduced-motion`.
