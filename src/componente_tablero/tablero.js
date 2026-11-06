// Tablero interactivo de MiniMate (componente de Streamlit, JS plano).
//
// Reparto de tareas:
// - chessboard.js (vendor/) dibuja el tablero, las piezas y el arrastrar-y-soltar.
// - chess.js (vendor/) sabe las reglas: jugadas legales, jaque, promoción...
// - Este archivo une las dos cosas y habla con Python.
// - Además dibuja la barra de evaluación, la flecha de la mejor jugada
//   (revisión) y los relojes.
//
// Protocolo con Streamlit (mensajes postMessage con el iframe padre):
//   nosotros -> Streamlit: "streamlit:componentReady"     (ya cargamos)
//   Streamlit -> nosotros: "streamlit:render"             (llegan los datos de Python)
//   nosotros -> Streamlit: "streamlit:setComponentValue"  (mandamos una jugada)
//   nosotros -> Streamlit: "streamlit:setFrameHeight"     (alto del iframe)

import { Chess } from './vendor/chess.js';

// ---------------------------------------------------------------------------
// Comunicación con Streamlit
// ---------------------------------------------------------------------------

function mandarAStreamlit(tipo, datos) {
  window.parent.postMessage({ isStreamlitMessage: true, type: tipo, ...datos }, '*');
}

function avisarQueEstamosListos() {
  mandarAStreamlit('streamlit:componentReady', { apiVersion: 1 });
}

function mandarValor(valor) {
  mandarAStreamlit('streamlit:setComponentValue', { value: valor, dataType: 'json' });
}

function ajustarAltura() {
  const alto = document.getElementById('contenedor').offsetHeight;
  mandarAStreamlit('streamlit:setFrameHeight', { height: alto });
}

// ---------------------------------------------------------------------------
// Estado del componente
// ---------------------------------------------------------------------------

let tablero = null;        // el dibujo (chessboard.js); se crea en el primer render
const juego = new Chess(); // las reglas (chess.js)
let piezas = {};           // { wK: "data:image/svg+xml;base64,...", ... } (vienen de Python)

let fenRecibido = null;    // último FEN que mandó Python
let miColor = 'w';         // 'w' o 'b'
let miTurno = false;       // Python dice si me toca
let ultima = null;         // última jugada { from: 'e2', to: 'e4' } para resaltarla

let seleccionada = null;        // casilla con la pieza elegida, ej: 'e2'
let estabaSeleccionada = false; // para saber si un clic en la pieza debe deseleccionarla
let promocionPendiente = null;  // { desde, hasta } mientras se elige la pieza
// Después de soltar una pieza el navegador puede mandar además un "click" del
// mismo gesto del mouse. Esta bandera lo ignora; se apaga al empezar un gesto nuevo.
let ignorarClic = false;

// Cuando mandamos una jugada esperamos que Python conteste.
// idEnviado identifica la jugada; Python nos devuelve "id_respondido".
let esperandoPython = false;
let idEnviado = null;

// Ayudas que manda Python (null = no se muestran).
let barra = null;    // { texto: '+1.5', porcentaje: 61.2 }  (porcentaje blanco)
let flecha = null;   // 'e2e4': mejor jugada en la revisión

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

function puedoMover() {
  return miTurno && !esperandoPython && !juego.isGameOver() && juego.turn() === miColor;
}

function casillaDOM(casilla) {
  return $(`#tablero [data-square="${casilla}"]`);
}

// Un id único para cada jugada que mandamos (fecha + número al azar).
function nuevoId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// Casilla del rey del bando que mueve (para marcar el jaque).
function casillaDelRey(color) {
  for (const fila of juego.board()) {
    for (const pieza of fila) {
      if (pieza && pieza.type === 'k' && pieza.color === color) return pieza.square;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Marcas de colores (última jugada, selección, destinos, jaque)
// ---------------------------------------------------------------------------

function dibujarMarcas() {
  // Borramos todas las marcas y las volvemos a poner.
  $('#tablero .square-55d63').removeClass('ultima seleccionada destino captura jaque');

  if (ultima) {
    casillaDOM(ultima.from).addClass('ultima');
    casillaDOM(ultima.to).addClass('ultima');
  }

  if (juego.inCheck()) {
    casillaDOM(casillaDelRey(juego.turn())).addClass('jaque');
  }

  if (seleccionada) {
    casillaDOM(seleccionada).addClass('seleccionada');
    // Un punto en cada destino legal, o un aro si es captura
    // (chess.js marca "captured" también en la captura al paso).
    for (const jugada of juego.moves({ square: seleccionada, verbose: true })) {
      casillaDOM(jugada.to).addClass(jugada.captured ? 'captura' : 'destino');
    }
  }

  document.body.classList.toggle('mi-turno', puedoMover());
}

function seleccionar(casilla) {
  seleccionada = casilla;
  dibujarMarcas();
}

function deseleccionar() {
  seleccionada = null;
  dibujarMarcas();
}

// ---------------------------------------------------------------------------
// Hacer jugadas
// ---------------------------------------------------------------------------

// Jugadas legales de "desde" a "hasta" (hay 4 si es promoción: una por pieza).
function jugadasEntre(desde, hasta) {
  return juego.moves({ square: desde, verbose: true }).filter((j) => j.to === hasta);
}

// Hace la jugada en chess.js y se la manda a Python.
// moverDibujo: si es true, también movemos la pieza en el dibujo (con animación).
// Cuando la jugada viene de arrastrar, la pieza ya está en su lugar.
function hacerJugada(desde, hasta, promocion, moverDibujo) {
  juego.move({ from: desde, to: hasta, promotion: promocion });
  if (moverDibujo) tablero.position(juego.fen(), true);

  ultima = { from: desde, to: hasta };
  seleccionada = null;
  esperandoPython = true;
  idEnviado = nuevoId();
  dibujarMarcas();

  // Mi reloj se frena mientras Python procesa la jugada.
  const usado = tiempoUsado();
  congelarMiReloj();

  // Le mandamos a Python la jugada en UCI, el FEN desde el que se jugó,
  // el id para que no la procese dos veces y cuántos segundos pensé.
  mandarValor({
    uci: desde + hasta + (promocion || ''), fen: fenRecibido, id: idEnviado,
    tiempo_usado: usado,
  });
}

// Intenta mover lo seleccionado a "hasta". Devuelve true si era un destino legal.
function intentarMover(desde, hasta, moverDibujo) {
  const opciones = jugadasEntre(desde, hasta);
  if (opciones.length === 0) return false;

  if (opciones.some((j) => j.promotion)) {
    abrirMenuPromocion(desde, hasta);   // primero hay que elegir la pieza
  } else {
    hacerJugada(desde, hasta, undefined, moverDibujo);
  }
  return true;
}

// ---------------------------------------------------------------------------
// Promoción
// ---------------------------------------------------------------------------

function abrirMenuPromocion(desde, hasta) {
  promocionPendiente = { desde, hasta };
  const opciones = $('#opciones-promocion').empty();
  const nombres = { q: 'Dama', r: 'Torre', b: 'Alfil', n: 'Caballo' };

  for (const letra of ['q', 'r', 'b', 'n']) {
    const imagen = piezas[miColor + letra.toUpperCase()];
    $('<button type="button">')
      .attr('title', nombres[letra])
      .attr('data-pieza', letra)
      .append($('<img>').attr('src', imagen).attr('alt', nombres[letra]))
      .on('click', () => elegirPromocion(letra))
      .appendTo(opciones);
  }
  $('#menu-promocion').prop('hidden', false);
}

function cerrarMenuPromocion() {
  promocionPendiente = null;
  $('#menu-promocion').prop('hidden', true);
}

function elegirPromocion(letra) {
  const { desde, hasta } = promocionPendiente;
  cerrarMenuPromocion();
  hacerJugada(desde, hasta, letra, true);
}

function cancelarPromocion() {
  cerrarMenuPromocion();
  // Si el peón se había arrastrado a la última fila, lo devolvemos.
  tablero.position(juego.fen(), false);
  deseleccionar();
}

// ---------------------------------------------------------------------------
// Clics
// ---------------------------------------------------------------------------

function alHacerClicEnCasilla(casilla) {
  if (!puedoMover()) return;

  // Si estaba eligiendo la promoción, cualquier clic en el tablero la cancela.
  if (promocionPendiente) {
    cancelarPromocion();
    return;
  }

  // ¿Es un destino de la pieza seleccionada? Entonces movemos.
  if (seleccionada && intentarMover(seleccionada, casilla, true)) return;

  // Si no: clic en otra pieza mía cambia la selección; cualquier otra cosa deselecciona.
  const pieza = juego.get(casilla);
  if (pieza && pieza.color === miColor && casilla !== seleccionada) {
    seleccionar(casilla);
  } else {
    deseleccionar();
  }
}

// ---------------------------------------------------------------------------
// Arrastrar y soltar (eventos de chessboard.js)
// ---------------------------------------------------------------------------
// Ojo: en chessboard.js un clic sobre una pieza propia también cuenta como
// "arrastre": empieza en onDragStart y termina en onDrop sobre la misma casilla.

function alEmpezarArrastre(origen, pieza) {
  // pieza viene como 'wP', 'bK'...: la primera letra es el color.
  if (!puedoMover() || promocionPendiente || pieza[0] !== miColor) return false;

  // Recordamos si ya estaba elegida: si el "arrastre" termina siendo un clic
  // en la misma casilla, un segundo clic la deselecciona.
  estabaSeleccionada = seleccionada === origen;
  seleccionar(origen);  // al agarrar una pieza mostramos sus destinos
  return true;
}

function alSoltar(origen, destino) {
  ignorarClic = true;

  // Soltó en la misma casilla = fue un clic sobre la pieza.
  if (origen === destino) {
    if (estabaSeleccionada) deseleccionar();  // segundo clic: deselecciona
    return;
  }

  // Fuera del tablero o a una casilla ilegal: la pieza vuelve a su lugar.
  if (destino === 'offboard' || !intentarMover(origen, destino, false)) {
    return 'snapback';
  }
  // Si llegamos acá la pieza queda donde la soltaron (o se abrió el menú de promoción).
}

function alTerminarAnimacion() {
  // Después de soltar, sincronizamos el dibujo con las reglas. Esto arregla
  // los casos especiales: la torre en el enroque, el peón comido al paso, etc.
  if (!promocionPendiente) tablero.position(juego.fen(), false);
}

// ---------------------------------------------------------------------------
// Barra de evaluación
// ---------------------------------------------------------------------------
// La parte clara es la ventaja de blancas (de 0 a 100%). Con blancas abajo
// crece desde abajo; jugando con negras está dada vuelta (blancas arriba).

function actualizarBarra() {
  const elemento = $('#barra');
  elemento.prop('hidden', !barra);
  if (!barra) return;

  const blancasAbajo = miColor === 'w';
  elemento.toggleClass('negras-abajo', !blancasAbajo);
  $('#barra-blancas').css('height', `${barra.porcentaje}%`);

  // El número va en la punta del que va ganando, con el color que contrasta.
  const ganaBlancas = barra.porcentaje >= 50;
  const enLaPuntaDeAbajo = ganaBlancas === blancasAbajo;
  $('#barra-texto')
    .text(barra.texto)
    .toggleClass('abajo', enLaPuntaDeAbajo)
    .toggleClass('arriba', !enLaPuntaDeAbajo)
    .toggleClass('sobre-blanco', ganaBlancas)
    .toggleClass('sobre-negro', !ganaBlancas);
}

// ---------------------------------------------------------------------------
// Flecha de la mejor jugada
// ---------------------------------------------------------------------------
// Es un dibujo SVG encima del tablero. Usamos un "viewBox" de 8x8: así
// cada casilla mide 1 y el centro de la casilla a1 (con blancas abajo) es
// el punto (0.5, 7.5), sin importar cuántos píxeles mida el tablero.

const SVG = 'http://www.w3.org/2000/svg';

function centroDeCasilla(casilla) {
  const columna = casilla.charCodeAt(0) - 'a'.charCodeAt(0);  // a=0 ... h=7
  const fila = Number(casilla[1]) - 1;                          // 1=0 ... 8=7
  if (tablero.orientation() === 'white') {
    return { x: columna + 0.5, y: 7 - fila + 0.5 };
  }
  return { x: 7 - columna + 0.5, y: fila + 0.5 };
}

function dibujarFlecha() {
  const svg = document.getElementById('flechas');
  svg.replaceChildren();  // borramos la flecha anterior
  if (!flecha || !tablero) return;

  // El SVG tiene que quedar justo encima de las casillas.
  const casillas = document.querySelector('#tablero .board-b72b1');
  if (!casillas) return;
  const zona = document.getElementById('zona-tablero').getBoundingClientRect();
  const rect = casillas.getBoundingClientRect();
  svg.style.left = `${rect.left - zona.left}px`;
  svg.style.top = `${rect.top - zona.top}px`;
  svg.style.width = `${rect.width}px`;
  svg.style.height = `${rect.height}px`;
  svg.setAttribute('viewBox', '0 0 8 8');

  const desde = centroDeCasilla(flecha.slice(0, 2));
  const hasta = centroDeCasilla(flecha.slice(2, 4));

  // Dirección de la flecha, de largo 1 (vector unitario).
  const largo = Math.hypot(hasta.x - desde.x, hasta.y - desde.y);
  const dx = (hasta.x - desde.x) / largo;
  const dy = (hasta.y - desde.y) / largo;

  // La punta queda un poco antes del centro de la casilla de destino,
  // y el palo termina donde empieza la punta.
  const punta = { x: hasta.x - dx * 0.15, y: hasta.y - dy * 0.15 };
  const base = { x: punta.x - dx * 0.45, y: punta.y - dy * 0.45 };
  const ancho = 0.28;  // media base del triángulo
  const color = 'rgba(21, 120, 27, 0.8)';

  const palo = document.createElementNS(SVG, 'line');
  palo.setAttribute('x1', desde.x);
  palo.setAttribute('y1', desde.y);
  palo.setAttribute('x2', base.x);
  palo.setAttribute('y2', base.y);
  palo.setAttribute('stroke', color);
  palo.setAttribute('stroke-width', '0.17');
  palo.setAttribute('stroke-linecap', 'round');

  // Triángulo: la punta y dos puntos a los costados de la base
  // (perpendicular a la dirección: (-dy, dx)).
  const triangulo = document.createElementNS(SVG, 'polygon');
  const puntos = [
    [punta.x, punta.y],
    [base.x - dy * ancho, base.y + dx * ancho],
    [base.x + dy * ancho, base.y - dx * ancho],
  ];
  triangulo.setAttribute('points', puntos.map((p) => p.join(',')).join(' '));
  triangulo.setAttribute('fill', color);

  svg.append(palo, triangulo);
}

// ---------------------------------------------------------------------------
// Relojes
// ---------------------------------------------------------------------------
// Python manda cuántos segundos le quedan a cada uno y cuál está corriendo:
//   reloj = { w: 297.5, b: 300, corre: 'w' }   (corre: null = ninguno)
// El que corre lo descontamos acá, en el navegador, para que se vea fluido.
// Cuando hago una jugada le mandamos a Python cuánto tiempo usé.
// Si se me acaba, le avisamos a Python (pierdo por tiempo).
// El tiempo del bot lo mide Python; acá solo lo mostramos bajando.

let reloj = null;             // último reloj que mandó Python
let claveReloj = null;        // para saber si Python mandó tiempos nuevos
let inicioConteo = 0;         // cuándo empezó a correr (performance.now(), en ms)
let miRelojCongelado = null;  // segundos que me quedaban al mandar la jugada
let avisoTiempoEnviado = false;

function actualizarReloj(nuevo, fen) {
  $('.reloj').prop('hidden', !nuevo);
  if (!nuevo) {
    reloj = null;
    claveReloj = null;
    return;
  }
  // Solo reiniciamos la cuenta si cambió algo (tiempos, quién corre o la
  // posición). Si Python volvió a correr por otro motivo (por ejemplo,
  // tocaste algo en la barra lateral, o rechazó una jugada), el reloj
  // sigue corriendo como venía.
  const clave = JSON.stringify(nuevo) + fen;
  if (clave !== claveReloj) {
    claveReloj = clave;
    reloj = nuevo;
    inicioConteo = performance.now();
    avisoTiempoEnviado = false;
  }
  miRelojCongelado = null;  // Python ya contestó: mi reloj vuelve a mostrarse normal
  // El rival arriba y yo abajo.
  $('#reloj-arriba .nombre').text('MiniMate');
  $('#reloj-abajo .nombre').text('Vos');
  tictac();
}

// Segundos que pasaron desde que empezó a correr mi reloj.
function tiempoUsado() {
  if (!reloj || reloj.corre !== miColor) return 0;
  return (performance.now() - inicioConteo) / 1000;
}

function congelarMiReloj() {
  if (reloj) miRelojCongelado = restante(miColor);
}

// Segundos que le quedan a un color ('w' o 'b'), contando lo que ya corrió.
function restante(color) {
  if (color === miColor && miRelojCongelado !== null) return miRelojCongelado;
  let segundos = reloj[color];
  if (reloj.corre === color) segundos -= (performance.now() - inicioConteo) / 1000;
  return Math.max(0, segundos);
}

// 125.3 -> "2:06";  menos de 10 segundos -> "0:07.4" (con décimas).
function formatearTiempo(segundos) {
  if (segundos < 10) {
    return `0:${segundos.toFixed(1).padStart(4, '0')}`;
  }
  const total = Math.ceil(segundos);
  const minutos = Math.floor(total / 60);
  const resto = String(total % 60).padStart(2, '0');
  return `${minutos}:${resto}`;
}

function dibujarUnReloj(selector, color) {
  const segundos = restante(color);
  const congelado = color === miColor && miRelojCongelado !== null;
  $(selector)
    .toggleClass('activo', reloj.corre === color && !congelado)
    .toggleClass('poco', segundos < 20)
    .find('.tiempo').text(formatearTiempo(segundos));
}

// Se llama 10 veces por segundo.
function tictac() {
  if (!reloj) return;
  const rival = miColor === 'w' ? 'b' : 'w';
  dibujarUnReloj('#reloj-abajo', miColor);
  dibujarUnReloj('#reloj-arriba', rival);

  // ¿Se me acabó el tiempo? Le avisamos a Python una sola vez.
  const meToca = reloj.corre === miColor && miTurno && !esperandoPython;
  if (meToca && !avisoTiempoEnviado && restante(miColor) <= 0) {
    avisoTiempoEnviado = true;
    cerrarMenuPromocion();
    seleccionada = null;
    esperandoPython = true;
    idEnviado = nuevoId();
    congelarMiReloj();
    dibujarMarcas();
    mandarValor({ tiempo_agotado: true, fen: fenRecibido, id: idEnviado });
  }
}

// ---------------------------------------------------------------------------
// Datos nuevos desde Python
// ---------------------------------------------------------------------------

function crearTablero(args) {
  piezas = args.piezas;
  tablero = Chessboard('tablero', {
    position: 'start',
    draggable: true,
    showNotation: true,                  // coordenadas a-h y 1-8
    pieceTheme: (nombre) => piezas[nombre],
    onDragStart: alEmpezarArrastre,
    onDrop: alSoltar,
    onSnapEnd: alTerminarAnimacion,
    moveSpeed: 250,
    snapSpeed: 80,
    snapbackSpeed: 200,
    appearSpeed: 150,
  });

  // Cada gesto nuevo (apretar el mouse o tocar la pantalla) apaga la bandera.
  // "true" = fase de captura: corre antes que los manejadores de chessboard.js.
  document.addEventListener('mousedown', () => { ignorarClic = false; }, true);
  document.addEventListener('touchstart', () => { ignorarClic = false; }, true);

  // Clics en las casillas (se usa "delegación": un solo manejador para todas).
  $('#tablero').on('click', '.square-55d63', function (evento) {
    if (ignorarClic) return;  // este clic es del arrastre: ya lo manejó alSoltar
    evento.stopPropagation(); // que no llegue al manejador de "clic afuera"
    alHacerClicEnCasilla($(this).attr('data-square'));
  });

  // Clic afuera del tablero (en el resto del iframe): deseleccionar.
  $(document).on('click', (evento) => {
    if (ignorarClic) return;
    if ($(evento.target).closest('#menu-promocion').length) return;
    if (seleccionada && !promocionPendiente) deseleccionar();
  });

  $('#cancelar-promocion').on('click', cancelarPromocion);

  prepararPantallaTactil();

  // Tamaño inicial, y de nuevo cada vez que cambie el ancho del iframe
  // o se gire la pantalla.
  ajustarTamano();
  $(window).on('resize', pedirAjusteDeTamano);
  if (screen.orientation) screen.orientation.addEventListener('change', pedirAjusteDeTamano);
  try {
    // La página de Streamlit (el "padre" del iframe): si cambia su alto
    // (por ejemplo al girar el celular) también recalculamos.
    window.parent.addEventListener('resize', pedirAjusteDeTamano);
  } catch (error) {
    // Si el navegador no nos deja acceder al padre, alcanza con lo de arriba.
  }
}

// ---------------------------------------------------------------------------
// Pantallas táctiles
// ---------------------------------------------------------------------------
// Problema: al arrastrar una pieza con el dedo, la página también se deslizaba.
// chessboard.js escucha "touchmove" en window, y los navegadores tratan esos
// listeners como "pasivos": su preventDefault() se ignora y el navegador scrollea.
//
// Solución:
// 1) CSS touch-action: none (en tablero.css) avisa de antemano que en el
//    tablero no hay que hacer scroll ni zoom.
// 2) Listeners propios con { passive: false } que llaman a preventDefault().
// 3) Como cancelar el touchstart también cancela el "click" que el navegador
//    genera al tocar, detectamos el toque nosotros (en touchend).

let inicioToque = null;  // { x, y } donde empezó el toque sobre el tablero

function prepararPantallaTactil() {
  const zonaTablero = document.getElementById('tablero');

  zonaTablero.addEventListener('touchstart', (evento) => {
    evento.preventDefault();  // sin scroll, sin zoom, sin "click" automático
    const dedo = evento.touches[0];
    inicioToque = { x: dedo.clientX, y: dedo.clientY };
  }, { passive: false });

  zonaTablero.addEventListener('touchmove', (evento) => {
    evento.preventDefault();
  }, { passive: false });

  // Lo registramos en window DESPUÉS de crear el tablero, así corre después
  // del touchend de chessboard.js (que es el que llama a alSoltar).
  window.addEventListener('touchend', (evento) => {
    if (!inicioToque) return;  // el toque no empezó en el tablero
    const inicio = inicioToque;
    inicioToque = null;

    // Si chessboard.js ya lo manejó (arrastre, o toque en una pieza propia), listo.
    if (ignorarClic) return;

    // Si el dedo se movió mucho fue un deslizamiento, no un toque.
    const dedo = evento.changedTouches[0];
    if (Math.hypot(dedo.clientX - inicio.x, dedo.clientY - inicio.y) > 10) return;

    // Toque en una casilla vacía o con pieza rival: lo tratamos igual que un clic.
    const elemento = document.elementFromPoint(dedo.clientX, dedo.clientY);
    const casilla = elemento && elemento.closest('.square-55d63');
    if (casilla) {
      ignorarClic = true;  // por si el navegador igual manda un click
      alHacerClicEnCasilla(casilla.dataset.square);
    }
  });
}

// ---------------------------------------------------------------------------
// Tamaño del tablero
// ---------------------------------------------------------------------------
// El tablero usa todo el ancho del iframe (en la compu es la columna de la
// izquierda, como antes; en el celular, el ancho de la pantalla). Pero no
// puede ser más alto que lo que se ve de la pantalla (celular acostado).

// Medidas fijas (las mismas que en tablero.css).
const ANCHO_BARRA = 26 + 6;   // ancho de la barra + separación con el tablero
const ALTO_RELOJ = 34 + 6;    // alto de un reloj + márgenes

function ajustarTamano() {
  const anchoDisponible = document.documentElement.clientWidth;

  let altoVisible = Infinity;
  try {
    altoVisible = window.parent.innerHeight;  // alto de la ventana del navegador
  } catch (error) {
    // Sin acceso al padre: limitamos solo por el ancho.
  }

  // Si hay barra, el tablero es un poco más angosto; si hay relojes,
  // un poco más bajo (para que todo entre en la pantalla).
  const anchoBarra = barra ? ANCHO_BARRA : 0;
  const altoRelojes = reloj ? 2 * ALTO_RELOJ : 0;
  const lado = Math.floor(Math.min(anchoDisponible - anchoBarra,
                                   altoVisible * 0.85 - altoRelojes));
  $('#tablero').css('width', `${lado}px`);
  tablero.resize();   // chessboard.js recalcula el tamaño de las casillas
  dibujarMarcas();    // resize() redibuja las casillas: volvemos a poner las marcas

  // La barra mide lo mismo que el tablero, y los relojes lo mismo que la fila.
  const altoTablero = $('#tablero .board-b72b1').outerHeight() || lado;
  $('#barra').css('height', `${altoTablero}px`);
  $('.reloj').css('width', `${$('#tablero').outerWidth() + anchoBarra}px`);
  dibujarFlecha();    // cambió el tamaño de las casillas

  ajustarAltura();    // el iframe tiene que medir lo mismo que el contenido
}

// Al girar la pantalla llegan varios eventos seguidos: los juntamos en uno
// solo por cuadro de animación.
let ajustePendiente = false;
function pedirAjusteDeTamano() {
  if (ajustePendiente) return;
  ajustePendiente = true;
  requestAnimationFrame(() => {
    ajustePendiente = false;
    ajustarTamano();
  });
}

function alRecibirDatos(args, tema) {
  if (!tablero) crearTablero(args);

  miColor = args.color === 'black' ? 'b' : 'w';
  miTurno = args.mi_turno;

  // Tema de Streamlit (claro u oscuro), para los colores de los relojes.
  document.body.classList.toggle('oscuro', Boolean(tema && tema.base === 'dark'));

  // Orientación: mi color abajo. (Cambiarla redibuja el tablero.)
  const orientacion = args.color === 'black' ? 'black' : 'white';
  if (tablero.orientation() !== orientacion) tablero.orientation(orientacion);

  // Si mandamos una jugada y Python todavía no la contestó, ignoramos este
  // render: puede traer la posición vieja y la pieza "volvería" atrás.
  const pythonContesto = args.id_respondido === idEnviado;
  if (esperandoPython && !pythonContesto) return;
  esperandoPython = false;

  if (args.fen !== fenRecibido) {
    // Posición nueva (jugada del bot, deshacer, partida nueva, jugada escrita...).
    // La primera vez la ponemos sin animación (si no, las piezas "volarían"
    // desde la posición inicial al recargar la página a mitad de partida).
    const primeraVez = fenRecibido === null;
    fenRecibido = args.fen;
    juego.load(args.fen);
    cerrarMenuPromocion();
    seleccionada = null;
    tablero.position(juego.fen(), !primeraVez);  // true = con animación
  } else if (juego.fen() !== new Chess(args.fen).fen()) {
    // Python contestó pero rechazó la jugada: volvemos a su posición.
    juego.load(args.fen);
    tablero.position(juego.fen(), true);
  }

  // Barra, flecha y reloj (después de la posición: la flecha va encima).
  // Si la barra o el reloj aparecen o desaparecen, cambia el lugar que le
  // queda al tablero: recalculamos el tamaño.
  const antes = `${Boolean(barra)}-${Boolean(reloj)}`;
  barra = args.barra || null;
  actualizarBarra();
  actualizarReloj(args.reloj || null, args.fen);
  if (`${Boolean(barra)}-${Boolean(reloj)}` !== antes) ajustarTamano();

  flecha = args.flecha || null;
  dibujarFlecha();

  ultima = args.ultima ? { from: args.ultima.slice(0, 2), to: args.ultima.slice(2, 4) } : null;
  dibujarMarcas();
  ajustarAltura();
}

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

window.addEventListener('message', (evento) => {
  if (evento.data && evento.data.type === 'streamlit:render') {
    alRecibirDatos(evento.data.args, evento.data.theme);
  }
});

// Ajustamos el alto del iframe cada vez que cambie el tamaño del contenido.
new ResizeObserver(ajustarAltura).observe(document.getElementById('contenedor'));

// El reloj se redibuja 10 veces por segundo.
setInterval(tictac, 100);

avisarQueEstamosListos();
