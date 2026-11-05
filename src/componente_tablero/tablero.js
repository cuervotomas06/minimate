// Tablero interactivo de MiniMate (componente de Streamlit, JS plano).
//
// Reparto de tareas:
// - chessboard.js (vendor/) dibuja el tablero, las piezas y el arrastrar-y-soltar.
// - chess.js (vendor/) sabe las reglas: jugadas legales, jaque, promoción...
// - Este archivo une las dos cosas y habla con Python.
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

  // Le mandamos a Python la jugada en UCI, el FEN desde el que se jugó
  // y el id para que no la procese dos veces.
  mandarValor({ uci: desde + hasta + (promocion || ''), fen: fenRecibido, id: idEnviado });
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

  // Si cambia el ancho (por ejemplo al girar el celular), redibujamos.
  $(window).on('resize', () => {
    tablero.resize();
    dibujarMarcas();
    ajustarAltura();
  });
}

function alRecibirDatos(args) {
  if (!tablero) crearTablero(args);

  miColor = args.color === 'black' ? 'b' : 'w';
  miTurno = args.mi_turno;

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

  ultima = args.ultima ? { from: args.ultima.slice(0, 2), to: args.ultima.slice(2, 4) } : null;
  dibujarMarcas();
  ajustarAltura();
}

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

window.addEventListener('message', (evento) => {
  if (evento.data && evento.data.type === 'streamlit:render') {
    alRecibirDatos(evento.data.args);
  }
});

// Ajustamos el alto del iframe cada vez que cambie el tamaño del contenido.
new ResizeObserver(ajustarAltura).observe(document.getElementById('contenedor'));

avisarQueEstamosListos();
