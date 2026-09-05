/* NÓRIA — salva-vidas.
 *
 * Um sistema de decisão não pode falhar em silêncio. Se o aplicativo não
 * subir, quem abriu a NÓRIA vê preto e não sabe se o servidor caiu, se o
 * navegador é velho ou se a internet dele engasgou. Este arquivo troca o
 * preto por uma explicação e por uma saída.
 *
 * Ele roda como script clássico, ANTES do módulo. Se o módulo nem carregar
 * (sintaxe que o navegador não entende, rede que caiu no meio), este aqui
 * já está de pé para contar o que houve.
 */
(function () {
  'use strict';

  var PRAZO = 12000;          // se em 12s nada foi pintado, algo travou
  var mostrou = false;
  var falhas = [];

  function pintado() {
    // A casca da aplicação ou a tela de entrada penduram conteúdo no body.
    var b = document.body;
    if (!b) return false;
    if (b.querySelector('.casca, .entrada, #abertura canvas')) return true;
    return (b.innerText || '').replace(/\s/g, '').length > 40;
  }

  function socorro(motivo) {
    if (mostrou) return;
    mostrou = true;
    var nav = navigator.userAgent || '';
    var caixa = document.createElement('div');
    caixa.setAttribute('id', 'salvavidas');
    caixa.setAttribute('style', [
      'position:fixed', 'inset:0', 'z-index:9999',
      'background:#101318', 'color:#F3F5F7',
      'font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
      'padding:32px 24px', 'overflow:auto', '-webkit-overflow-scrolling:touch',
    ].join(';'));

    caixa.innerHTML =
      '<div style="max-width:560px;margin:0 auto">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:28px">' +
      '<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">' +
      '<g stroke="#50D6BC" stroke-width="1.6" fill="none">' +
      '<circle cx="16" cy="16" r="11" opacity=".4"/>' +
      '<circle cx="16" cy="16" r="4" fill="#50D6BC"/></g></svg>' +
      '<strong style="font-size:19px;letter-spacing:.04em">NÓRIA</strong></div>' +
      '<h1 style="font-size:23px;font-weight:700;margin:0 0 12px">A interface não subiu neste navegador</h1>' +
      '<p style="color:#ADB7C6;margin:0 0 26px">' +
      'O servidor respondeu e os arquivos chegaram. O que travou foi a montagem ' +
      'da tela aqui no seu aparelho. Abaixo está o motivo exato — mande esta tela ' +
      'para mim que eu corrijo.</p>' +
      '<div style="background:#191E26;border:1px solid #2A323F;border-radius:10px;padding:16px 18px;margin-bottom:26px">' +
      '<div style="font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#6F7B8C;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px">Motivo</div>' +
      '<div id="sv-motivo" style="font:13px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;color:#F08080;word-break:break-word;white-space:pre-wrap"></div>' +
      '<div style="font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#6F7B8C;letter-spacing:.08em;text-transform:uppercase;margin:18px 0 10px">Navegador</div>' +
      '<div id="sv-nav" style="font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:#ADB7C6;word-break:break-word"></div>' +
      '</div>' +
      '<div style="display:flex;gap:12px;flex-wrap:wrap">' +
      '<button id="sv-limpar" style="background:#50D6BC;color:#0B0E12;border:0;border-radius:8px;padding:12px 20px;font-size:15px;font-weight:600;cursor:pointer">Limpar e tentar de novo</button>' +
      '<button id="sv-recarregar" style="background:transparent;color:#F3F5F7;border:1px solid #2A323F;border-radius:8px;padding:12px 20px;font-size:15px;cursor:pointer">Só recarregar</button>' +
      '</div></div>';

    document.body.appendChild(caixa);
    caixa.querySelector('#sv-motivo').textContent =
      motivo + (falhas.length ? '\n\n' + falhas.join('\n') : '');
    caixa.querySelector('#sv-nav').textContent = nav + '\n' + screen.width + '×' + screen.height;

    caixa.querySelector('#sv-recarregar').onclick = function () { location.reload(); };
    caixa.querySelector('#sv-limpar').onclick = function () {
      // Sessão velha e abertura marcada são a causa mais comum de tela morta.
      try { localStorage.clear(); } catch (e) { /* bloqueado */ }
      try { sessionStorage.clear(); } catch (e) { /* bloqueado */ }
      location.reload();
    };
  }

  window.addEventListener('error', function (ev) {
    if (ev && ev.target && ev.target.tagName === 'SCRIPT') {
      falhas.push('não carregou: ' + (ev.target.src || '?'));
      socorro('Um arquivo do sistema não chegou ao navegador.');
      return;
    }
    var m = (ev && ev.message) || 'erro desconhecido';
    if (ev && ev.filename) m += '\n' + ev.filename + ':' + ev.lineno;
    falhas.push(m);
    socorro('O código parou com erro.');
  }, true);

  window.addEventListener('unhandledrejection', function (ev) {
    var r = ev && ev.reason;
    falhas.push('promessa rejeitada: ' + ((r && (r.message || r)) || '?'));
    socorro('Uma chamada ao servidor falhou e ninguém tratou.');
  });

  window.addEventListener('load', function () {
    setTimeout(function () {
      if (!pintado()) {
        socorro('Passaram ' + (PRAZO / 1000) + ' segundos e nada foi desenhado na tela.');
      }
    }, PRAZO);
  });

  // A aplicação avisa quando conseguiu pintar; aí o salva-vidas se cala.
  window.addEventListener('noria:vivo', function () { mostrou = true; });
})();
