const DEFAULT_ENDPOINT = 'http://127.0.0.1:8765';
const ENDPOINT_KEY = 'blundermate_lab_ocr_endpoint';

const fileInput = document.getElementById('fileInput');
const dropzone = document.getElementById('dropzone');
const pasteBtn = document.getElementById('pasteBtn');
const clearBtn = document.getElementById('clearBtn');
const checkBtn = document.getElementById('checkBtn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const resultsPanel = document.getElementById('resultsPanel');
const previewWrap = document.getElementById('previewWrap');
const imagePreview = document.getElementById('imagePreview');
const healthBadge = document.getElementById('healthBadge');
const endpointInput = document.getElementById('endpointInput');
const openLocalLink = document.getElementById('openLocalLink');
const boardTemplate = document.getElementById('boardTemplate');

endpointInput.value = localStorage.getItem(ENDPOINT_KEY) || DEFAULT_ENDPOINT;

function endpoint() {
  return endpointInput.value.trim().replace(/\/+$/, '') || DEFAULT_ENDPOINT;
}

function saveEndpoint() {
  localStorage.setItem(ENDPOINT_KEY, endpoint());
  openLocalLink.href = `${endpoint()}/`;
}

function setStatus(text) {
  statusEl.textContent = text;
}

function renderEmptyState(title = 'Waiting for a board image', body = 'Drop or paste a screenshot and the detected FEN will appear here.') {
  const empty = document.createElement('div');
  empty.className = 'empty-result';

  const strong = document.createElement('strong');
  strong.textContent = title;

  const text = document.createElement('span');
  text.textContent = body;

  empty.append(strong, text);
  resultsEl.replaceChildren(empty);
}

function formatPct(value) {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '-';
}

function parsePlacement(placement) {
  const cells = [];
  for (const rank of placement.split('/')) {
    for (const ch of rank) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < Number(ch); i += 1) cells.push('');
      } else {
        cells.push(ch);
      }
    }
  }
  return cells.length === 64 ? cells : Array(64).fill('');
}

function squareName(index) {
  const row = Math.floor(index / 8);
  const col = index % 8;
  return `${String.fromCharCode(97 + col)}${8 - row}`;
}

function pieceKey(piece) {
  if (!piece) return '';
  const color = piece === piece.toUpperCase() ? 'w' : 'b';
  return `${color}${piece.toUpperCase()}`;
}

function confidenceClass(value) {
  if (typeof value !== 'number') return 'unknown';
  if (value < 0.85) return 'low';
  if (value < 0.94) return 'mid';
  return 'high';
}

function renderPiece(piece) {
  const key = pieceKey(piece);
  if (!key) return null;
  const img = document.createElement('img');
  img.className = 'piece';
  img.alt = '';
  img.decoding = 'async';
  img.draggable = false;
  img.src = `/pieces/cburnett/${key}.svg`;
  return img;
}

function renderBoard(el, board) {
  const cells = parsePlacement(board.fen || '');
  const flipped = board.orientation === 'flipped';
  const pieceConfs = board.pieceConfs || {};

  el.innerHTML = '';
  for (let visualIdx = 0; visualIdx < 64; visualIdx += 1) {
    const sourceIdx = flipped ? 63 - visualIdx : visualIdx;
    const piece = cells[sourceIdx];
    const sq = document.createElement('div');
    const row = Math.floor(visualIdx / 8);
    const col = visualIdx % 8;
    const algebraic = squareName(sourceIdx);

    sq.className = `sq ${(row + col) % 2 === 0 ? 'light' : 'dark'}`;
    sq.title = piece ? `${algebraic} - ${formatPct(pieceConfs[algebraic])}` : algebraic;

    const renderedPiece = renderPiece(piece);
    if (renderedPiece) sq.appendChild(renderedPiece);

    if (col === 0) {
      const rank = document.createElement('span');
      rank.className = 'coord coord-rank';
      rank.textContent = algebraic[1];
      sq.appendChild(rank);
    }

    if (row === 7) {
      const file = document.createElement('span');
      file.className = 'coord coord-file';
      file.textContent = algebraic[0];
      sq.appendChild(file);
    }

    el.appendChild(sq);
  }
}

function metric(label, value) {
  const row = document.createElement('div');
  const dt = document.createElement('dt');
  const dd = document.createElement('dd');
  dt.textContent = label;
  dd.textContent = value;
  row.append(dt, dd);
  return row;
}

function badge(text, tone = '') {
  const el = document.createElement('span');
  el.className = `badge ${tone}`.trim();
  el.textContent = text;
  return el;
}

function renderResults(data) {
  resultsEl.innerHTML = '';
  const boards = Array.isArray(data.boards) ? data.boards : [];

  if (boards.length === 0) {
    setStatus(`No board found. Processed in ${data.elapsedMs ?? '-'}ms.`);
    renderEmptyState('No board found', 'Try a cleaner crop with the whole 2D board visible.');
    return;
  }

  setStatus(`${boards.length} board${boards.length === 1 ? '' : 's'} detected in ${data.elapsedMs ?? '-'}ms.`);

  boards.forEach((board, index) => {
    const node = boardTemplate.content.firstElementChild.cloneNode(true);
    const fullFen = board.fullFen || `${board.fen} ${board.turn || 'w'} - - 0 1`;
    const toMove = board.turn === 'b' ? 'Black' : 'White';
    const orientation = board.orientation === 'flipped' ? 'black at bottom' : 'white at bottom';

    node.querySelector('h2').textContent = `Board ${index + 1}`;
    node.querySelector('textarea').value = fullFen;
    node.querySelector('.board-caption').textContent = `Detected view: ${orientation}`;
    renderBoard(node.querySelector('.board'), board);

    node.querySelector('.result-badges').append(
      badge(`${toMove} to move`, 'strong'),
      badge(`board ${formatPct(board.boardConf)}`),
      badge(`min piece ${formatPct(board.minPieceConf)}`, confidenceClass(board.minPieceConf)),
    );

    node.querySelector('.metrics').append(
      metric('turn', board.turn || '-'),
      metric('board conf', formatPct(board.boardConf)),
      metric('min piece conf', formatPct(board.minPieceConf)),
      metric('orientation', board.orientation || 'unknown'),
      metric('turn conf', formatPct(board.turnConf)),
      metric('pieces', String(board.pieceCount ?? '-')),
    );

    node.querySelector('.copy-btn').addEventListener('click', async () => {
      await navigator.clipboard.writeText(fullFen);
      setStatus('FEN copied to clipboard.');
    });

    resultsEl.appendChild(node);
  });

  if (window.matchMedia('(max-width: 760px)').matches) {
    requestAnimationFrame(() => {
      resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
}

async function checkHealth() {
  saveEndpoint();
  try {
    const response = await fetch(`${endpoint()}/health`, { mode: 'cors' });
    const data = await response.json();
    healthBadge.textContent = data.ok ? 'ready' : 'error';
    healthBadge.className = `health ${data.ok ? 'ok' : 'bad'}`;
    setStatus(data.ok ? 'Local OCR server is ready.' : 'Local OCR server returned an error.');
  } catch {
    healthBadge.textContent = 'offline';
    healthBadge.className = 'health bad';
    setStatus('Local OCR server is offline. Start the downloaded server with start.ps1 first.');
  }
}

async function analyzeFile(file) {
  if (!file) return;

  saveEndpoint();
  previewWrap.classList.remove('hidden');
  imagePreview.src = URL.createObjectURL(file);
  renderEmptyState('Reading the board', 'The OCR server is working on this screenshot.');
  setStatus('Reading the board from the image...');
  fileInput.disabled = true;
  pasteBtn.disabled = true;

  const form = new FormData();
  form.append('file', file);

  try {
    const response = await fetch(`${endpoint()}/api/ocr`, {
      method: 'POST',
      mode: 'cors',
      body: form,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderResults(await response.json());
  } catch (error) {
    setStatus(`Recognition failed: ${error.message}`);
  } finally {
    fileInput.disabled = false;
    pasteBtn.disabled = false;
  }
}

fileInput.addEventListener('change', () => analyzeFile(fileInput.files?.[0]));
checkBtn.addEventListener('click', checkHealth);
endpointInput.addEventListener('change', checkHealth);

dropzone.addEventListener('dragover', (event) => {
  event.preventDefault();
  dropzone.classList.add('dragging');
});

dropzone.addEventListener('dragleave', () => {
  dropzone.classList.remove('dragging');
});

dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropzone.classList.remove('dragging');
  analyzeFile(event.dataTransfer?.files?.[0]);
});

pasteBtn.addEventListener('click', async () => {
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find((type) => type.startsWith('image/'));
      if (!imageType) continue;

      const blob = await item.getType(imageType);
      await analyzeFile(new File([blob], 'clipboard-image.png', { type: imageType }));
      return;
    }
    setStatus('No image found on the clipboard.');
  } catch (error) {
    setStatus(`Clipboard read failed: ${error.message}`);
  }
});

clearBtn.addEventListener('click', () => {
  fileInput.value = '';
  imagePreview.removeAttribute('src');
  previewWrap.classList.add('hidden');
  renderEmptyState();
  setStatus('Drop an image to see the detected board and FEN.');
});

saveEndpoint();
renderEmptyState();
checkHealth();
