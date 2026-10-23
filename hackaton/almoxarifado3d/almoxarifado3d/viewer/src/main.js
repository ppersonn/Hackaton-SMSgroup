/* Simulador 3D de almoxarifado: reproduz um dia gravado pelo motor Python.
   Duas vistas (referência x cenário escolhido) compartilham o mesmo relógio. */
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('dados').textContent);
  var LAY = D.layout, META = D.meta, TEC = META.tecnologias;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var nf = function (v, d) { return v.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }); };
  var clamp = function (x, a, b) { return Math.max(a, Math.min(b, x)); };
  function ub(a, x) { var lo = 0, hi = a.length; while (lo < hi) { var m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; }
  function lb(a, x) { var lo = 0, hi = a.length; while (lo < hi) { var m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
  function hms(s) {
    s = Math.max(0, Math.floor(s));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m + ':' + (x < 10 ? '0' : '') + x;
  }
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  /* ------------------------------------------------------------- dados */
  var SC = D.cenarios;
  var T0 = META.turno_ini_h * 3600;
  function prep(sc) {
    if (sc._p) return sc._p;
    var d = sc.dia, p = { segs: d.segs, evts: d.evts, delta: d.delta }, i;
    p.evtT = d.evts.map(function (e) { return e.t; });
    p.times = {};
    d.evts.forEach(function (e) { (p.times[e.tipo] = p.times[e.tipo] || []).push(e.t); });
    p.mis = [];
    d.evts.forEach(function (e) {
      if (e.tipo === 'endereco_errado') p.mis.push([e.t, e.item, 1]);
      else if (e.tipo === 'localizado' || e.tipo === 'ajuste') p.mis.push([e.t, e.item, 0]);
    });
    p.deltaT = d.delta.map(function (x) { return x[0]; });
    p.misT = p.mis.map(function (x) { return x[0]; });
    p.segT = d.segs.map(function (arr) { return arr.map(function (x) { return x[0]; }); });
    var tmax = 0;
    d.segs.forEach(function (arr) { if (arr.length) tmax = Math.max(tmax, arr[arr.length - 1][1]); });
    if (p.evtT.length) tmax = Math.max(tmax, p.evtT[p.evtT.length - 1]);
    p.tmax = tmax;
    sc._p = p;
    return p;
  }
  var TMAX = T0 + META.turno_h * 3600 + 600;
  SC.forEach(function (sc) { TMAX = Math.max(TMAX, prep(sc).tmax + 60); });
  function findSc(r, v, s) {
    for (var i = 0; i < SC.length; i++) if (SC[i].rfid === r && SC[i].visao === v && SC[i].smartstock === s) return i;
    return 0;
  }

  var nPos = 0;
  LAY.posicoes.forEach(function (p) { nPos = Math.max(nPos, p.baia + 1); });
  var BAIA = LAY.comprimento_rack / nPos;
  var ALT = LAY.altura_nivel, HR = LAY.niveis * ALT;
  var itemPos = LAY.itens.map(function (it) { return LAY.posicoes[it.posicao]; });

  /* -------------------------------------------------------- atividades */
  var ACT = {
    andar: ['caminhando', '#4aa3df'], ler: ['lendo endereço', '#8e9aa3'], busca: ['procurando item', '#e0b252'],
    pega: ['movimentando item', '#3fae6a'], corrige: ['corrigindo erro', '#ef6f60'],
    conf: ['conferindo expedição', '#7c8cf8'], receb: ['recebendo lote', '#2bb5a8'],
    contagem: ['contando estoque', '#2bb5a8'], alerta: ['verificando alerta', '#e0b252'],
    livre: ['aguardando', '#8a979e']
  };
  var EFF = {
    rfid_contagem: { k: 'ring', c: '#2bb5a8', life: 1.3, at: 'item' },
    rfid_expedicao: { k: 'ring', c: '#2bb5a8', life: 1.3, at: 'exp' },
    rfid_recebimento: { k: 'ring', c: '#2bb5a8', life: 1.3, at: 'rec' },
    camera: { k: 'beam', c: '#38bdf8', life: 0.55, at: 'item' },
    camera_corrige: { k: 'beam', c: '#3fae6a', life: 0.9, at: 'item', pulse: '#3fae6a' },
    erro: { k: 'pulse', c: '#ef4444', life: 1.4, at: 'item', s: 0.9 },
    ruptura: { k: 'pulse', c: '#ef4444', life: 1.8, at: 'item', s: 1.4 },
    sem_baixa: { k: 'pulse', c: '#ff9f1c', life: 1.3, at: 'item', s: 0.8 },
    endereco_errado: { k: 'pulse', c: '#a855f7', life: 1.5, at: 'item', s: 0.9 },
    alerta_falso: { k: 'pulse', c: '#facc15', life: 1.3, at: 'item', s: 0.8 },
    localizado: { k: 'pulse', c: '#3fae6a', life: 1.0, at: 'item', s: 0.6 },
    ajuste: { k: 'pulse', c: '#2bb5a8', life: 1.2, at: 'item', s: 0.7 },
    erro_recebimento: { k: 'pulse', c: '#ef4444', life: 1.6, at: 'rec', s: 1.4 },
    pedido_compra: { k: 'pulse', c: '#7c8cf8', life: 1.4, at: 'board', s: 1.2 }
  };

  /* ---------------------------------------------------------- sprites */
  function label(text, w, h) {
    var c = document.createElement('canvas'); c.width = 512; c.height = Math.round(512 * h / w);
    var g = c.getContext('2d');
    g.fillStyle = 'rgba(18,26,31,0.82)';
    var r = 18, W = c.width, H = c.height;
    g.beginPath(); g.moveTo(r, 0); g.lineTo(W - r, 0); g.quadraticCurveTo(W, 0, W, r); g.lineTo(W, H - r);
    g.quadraticCurveTo(W, H, W - r, H); g.lineTo(r, H); g.quadraticCurveTo(0, H, 0, H - r); g.lineTo(0, r);
    g.quadraticCurveTo(0, 0, r, 0); g.closePath(); g.fill();
    g.fillStyle = '#e8eef1';
    var fs = Math.round(H * 0.5);
    g.font = '600 ' + fs + 'px "IBM Plex Sans", Arial, sans-serif';
    var tw = g.measureText(text).width;
    if (tw > W * 0.9) { fs = Math.floor(fs * W * 0.9 / tw); g.font = '600 ' + fs + 'px "IBM Plex Sans", Arial, sans-serif'; }
    g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, W / 2, H / 2 + 2);
    var t = new THREE.CanvasTexture(c);
    var s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthTest: false }));
    s.scale.set(w, h, 1); s.renderOrder = 10;
    return s;
  }

  /* -------------------------------------------------------------- pane */
  var panes = [];
  var syncCam = true, syncing = false, dirtyAll = true;

  function makePane(root, idx) {
    var P = { root: root, idx: idx, dirty: true, last: {} };
    var holder = $('.cv', root);
    var renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    holder.appendChild(renderer.domElement);
    var scene = new THREE.Scene();
    var W = LAY.largura, Dp = LAY.profundidade;
    var camera = new THREE.PerspectiveCamera(42, 1, 0.5, 600);
    camera.position.set(W * 0.5, Math.max(W, Dp) * 0.92, Dp + Math.max(W, Dp) * 0.2);
    var controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(W * 0.5, 0, Dp * 0.46);
    controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 6; controls.maxDistance = 140;
    controls.update();
    controls.addEventListener('change', function () {
      P.dirty = true; dirtyAll = true;
      if (syncCam && !syncing) {
        syncing = true;
        panes.forEach(function (o) {
          if (o !== P) { o.camera.position.copy(camera.position); o.controls.target.copy(controls.target); o.controls.update(); o.dirty = true; }
        });
        syncing = false;
      }
    });
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8c9aa6, 0.9));
    var sun = new THREE.DirectionalLight(0xffffff, 0.55); sun.position.set(W * 0.3, 30, Dp * 0.1); scene.add(sun);
    P.scene = scene; P.camera = camera; P.controls = controls; P.renderer = renderer;

    /* chão, pátio, muretas */
    var yard = new THREE.Mesh(new THREE.PlaneGeometry(W + 80, Dp + 120), new THREE.MeshLambertMaterial({ color: 0x20282c }));
    yard.rotation.x = -Math.PI / 2; yard.position.set(W / 2, -0.03, Dp / 2 - 30); scene.add(yard);
    var slab = new THREE.Mesh(new THREE.PlaneGeometry(W, Dp), new THREE.MeshLambertMaterial({ color: 0x2a343a }));
    slab.rotation.x = -Math.PI / 2; slab.position.set(W / 2, 0, Dp / 2); scene.add(slab);
    P.mats = { yard: yard.material, slab: slab.material };
    var laneMat = new THREE.MeshLambertMaterial({ color: 0x35424a }); P.mats.lane = laneMat;
    function lane(x, z, w, d, mat) {
      var m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat);
      m.rotation.x = -Math.PI / 2; m.position.set(x, 0.012, z); scene.add(m);
    }
    lane(W / 2, LAY.z_cruz, W, LAY.largura_corredor, laneMat);
    LAY.x_corredores.forEach(function (x) { lane(x, LAY.z_racks + LAY.comprimento_rack / 2, LAY.largura_corredor, LAY.comprimento_rack + 0.4, laneMat); });
    var padMat = new THREE.MeshBasicMaterial({ color: 0xe0b252, transparent: true, opacity: 0.28 });
    lane(LAY.recebimento[0], LAY.recebimento[1], 5, 4.4, padMat);
    lane(LAY.expedicao[0], LAY.expedicao[1], 5, 4.4, padMat);
    var wallMat = new THREE.MeshLambertMaterial({ color: 0x6b7a84 });
    function wall(x, z, w, d) { var m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.45, d), wallMat); m.position.set(x, 0.225, z); scene.add(m); }
    wall(W / 2, -0.1, W, 0.2); wall(W / 2, Dp + 0.1, W, 0.2); wall(-0.1, Dp / 2, 0.2, Dp); wall(W + 0.1, Dp / 2, 0.2, Dp);

    /* racks: montantes azuis e longarinas laranja */
    var bm = new THREE.MeshLambertMaterial({ color: 0xe8832a }), um = new THREE.MeshLambertMaterial({ color: 0x2f5d8a });
    var upCount = LAY.x_racks.length * (nPos + 1) * 2 * 2;
    var ups = new THREE.InstancedMesh(new THREE.BoxGeometry(0.09, HR + 0.25, 0.09), um, upCount), k = 0, dm = new THREE.Object3D();
    LAY.x_racks.forEach(function (xr) {
      for (var n = 0; n <= LAY.niveis; n++) {
        [-1, 1].forEach(function (sd) {
          var b = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.1, LAY.comprimento_rack), bm);
          b.position.set(xr + sd * (LAY.prof_rack / 2 - 0.05), n * ALT, LAY.z_racks + LAY.comprimento_rack / 2); scene.add(b);
        });
      }
      for (var i = 0; i <= nPos; i++) for (var s = -1; s <= 1; s += 2) for (var q = 0; q < 2; q++) {
        dm.position.set(xr + s * (LAY.prof_rack / 2 - 0.05), (HR + 0.25) / 2, LAY.z_racks + i * BAIA + (q ? 0.04 : -0.04));
        dm.updateMatrix(); ups.setMatrixAt(k++, dm.matrix);
      }
    });
    scene.add(ups);

    /* itens: uma caixa por item, altura = nível de estoque físico */
    var shelfMat = new THREE.MeshLambertMaterial({ color: 0x8b98a1 });
    var boxGeo = new THREE.BoxGeometry(1, 1, 1), mkGeo = new THREE.SphereGeometry(0.17, 12, 8);
    P.box = []; P.mk = [];
    LAY.itens.forEach(function (it, i) {
      var ps = itemPos[i];
      var sh = new THREE.Mesh(boxGeo, shelfMat); sh.scale.set(LAY.prof_rack * 0.46, 0.04, BAIA - 0.12);
      sh.position.set(ps.pos[0], ps.nivel * ALT + 0.03, ps.pos[2]); scene.add(sh);
      var m = new THREE.Mesh(boxGeo, new THREE.MeshLambertMaterial({ color: 0x3fae6a }));
      m.position.set(ps.pos[0], ps.nivel * ALT + 0.1, ps.pos[2]); m.scale.set(0.84, 0.05, 1.2); scene.add(m); P.box.push(m);
      var q = new THREE.Mesh(mkGeo, new THREE.MeshBasicMaterial({ color: 0xff9f1c }));
      var sign = ps.face ? 1 : -1;
      q.position.set(ps.pos[0] + sign * 0.66, ps.nivel * ALT + 0.28, ps.pos[2]); q.visible = false; scene.add(q); P.mk.push(q);
    });

    /* operadores */
    P.ops = [];
    for (var o = 0; o < META.n_operadores; o++) {
      var g = new THREE.Group(), mat = new THREE.MeshLambertMaterial({ color: 0x4aa3df });
      var body = new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.3, 1.25, 14), mat); body.position.y = 0.65; g.add(body);
      var head = new THREE.Mesh(new THREE.SphereGeometry(0.21, 14, 10), new THREE.MeshLambertMaterial({ color: 0xf1d2b0 })); head.position.y = 1.45; g.add(head);
      var hat = new THREE.Mesh(new THREE.SphereGeometry(0.23, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshLambertMaterial({ color: 0xffd23f })); hat.position.y = 1.5; g.add(hat);
      var tag = label('Op ' + (o + 1), 1.0, 0.36); tag.position.y = 2.15; g.add(tag);
      g.scale.set(1.45, 1.45, 1.45); scene.add(g); P.ops.push({ g: g, mat: mat });
    }

    /* tecnologias (aparecem e somem conforme o cenário) */
    P.rfid = new THREE.Group(); P.visao = new THREE.Group(); P.smart = new THREE.Group();
    var tm = new THREE.MeshLambertMaterial({ color: 0x1aa59a });
    function gate(pt) {
      [-1.6, 1.6].forEach(function (dz) {
        var p = new THREE.Mesh(new THREE.BoxGeometry(0.14, 2.7, 0.14), tm); p.position.set(pt[0], 1.35, pt[1] + dz); P.rfid.add(p);
      });
      var t = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 3.4), tm); t.position.set(pt[0], 2.7, pt[1]); P.rfid.add(t);
      var l = label('Portal RFID', 1.9, 0.5); l.position.set(pt[0], 3.5, pt[1]); P.rfid.add(l);
    }
    gate(LAY.recebimento); gate(LAY.expedicao);
    LAY.x_racks.forEach(function (xr) {
      [LAY.z_racks - 0.25, LAY.z_racks + LAY.comprimento_rack + 0.25].forEach(function (z) {
        var p = new THREE.Mesh(new THREE.BoxGeometry(0.08, HR + 0.5, 0.08), tm); p.position.set(xr, (HR + 0.5) / 2, z); P.rfid.add(p);
        var a = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.45, 0.1), tm); a.position.set(xr, HR + 0.55, z); P.rfid.add(a);
      });
    });
    var cm = new THREE.MeshLambertMaterial({ color: 0x1c6fb0 });
    P.cams = [];
    LAY.x_corredores.forEach(function (x) {
      var z = LAY.z_racks + LAY.comprimento_rack + 0.7, y = HR + 1.1;
      var pole = new THREE.Mesh(new THREE.BoxGeometry(0.08, y, 0.08), cm); pole.position.set(x, y / 2, z); P.visao.add(pole);
      var cam = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.24, 0.5), cm); cam.position.set(x, y, z - 0.1); P.visao.add(cam);
      var cone = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.6, 4, 1, true), new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false }));
      cone.rotation.x = -Math.PI / 2; cone.position.set(x, y - 0.1, z - 1.5); P.visao.add(cone);
      P.cams.push([x, y, z]);
    });
    var vl = label('Câmeras nos corredores', 3.2, 0.5); vl.position.set(W / 2, HR + 2.6, LAY.z_racks + LAY.comprimento_rack + 1.2); P.visao.add(vl);
    var board = label('SmartStock: reposição adaptativa', 6.6, 0.95); board.position.set(W / 2, 3.4, 0.3); P.smart.add(board);
    P.boardPos = [W / 2, 3.4, 0.3];
    scene.add(P.rfid); scene.add(P.visao); scene.add(P.smart);

    var lr = label('Recebimento', 2.8, 0.55); lr.position.set(LAY.recebimento[0], 0.2, LAY.recebimento[1] - 3.1); scene.add(lr);
    var le = label('Expedição', 2.4, 0.55); le.position.set(LAY.expedicao[0], 0.2, LAY.expedicao[1] - 3.1); scene.add(le);

    /* caminhões */
    P.trucks = [];
    for (var tI = 0; tI < 3; tI++) {
      var tg = new THREE.Group();
      var cargo = new THREE.Mesh(new THREE.BoxGeometry(2.7, 2.9, 6.4), new THREE.MeshLambertMaterial({ color: 0xcfd6da })); cargo.position.set(0, 1.9, -1.0); tg.add(cargo);
      var cab = new THREE.Mesh(new THREE.BoxGeometry(2.6, 2.1, 1.7), new THREE.MeshLambertMaterial({ color: 0x2f5d8a })); cab.position.set(0, 1.45, -5.0); tg.add(cab);
      tg.position.set(LAY.recebimento[0], 0, -2.6 - tI * 8.5); tg.visible = false; scene.add(tg); P.trucks.push(tg);
    }

    /* efeitos reutilizáveis */
    P.pulses = []; P.rings = []; P.beams = [];
    var sph = new THREE.SphereGeometry(1, 12, 8), rg = new THREE.RingGeometry(0.86, 1, 36);
    for (var a = 0; a < 28; a++) {
      var pm = new THREE.Mesh(sph, new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false })); pm.visible = false; scene.add(pm); P.pulses.push(pm);
    }
    for (a = 0; a < 18; a++) {
      var rm = new THREE.Mesh(rg, new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      rm.rotation.x = -Math.PI / 2; rm.visible = false; scene.add(rm); P.rings.push(rm);
    }
    for (a = 0; a < 18; a++) {
      var geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)]);
      var ln = new THREE.Line(geo, new THREE.LineBasicMaterial({ transparent: true })); ln.visible = false; ln.frustumCulled = false; scene.add(ln); P.beams.push(ln);
    }

    /* tamanho */
    function resize() {
      var w = holder.clientWidth, h = holder.clientHeight;
      if (w < 2 || h < 2) return;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); P.dirty = true; dirtyAll = true;
    }
    if (window.ResizeObserver) new ResizeObserver(resize).observe(holder); else window.addEventListener('resize', resize);
    resize();

    P.hud = { k: $('.hud-k', root), o: $('.hud-o', root), chips: $$('.chip', root), title: $('.ptitle', root) };
    P.phys = new Int32Array(LAY.itens.length); P.sys = new Int32Array(LAY.itens.length); P.mis0 = new Uint8Array(LAY.itens.length);
    P.setScenario = function (i) {
      P.idx = i; var sc = SC[i]; prep(sc);
      P.rfid.visible = !!sc.rfid; P.visao.visible = !!sc.visao; P.smart.visible = !!sc.smartstock;
      P.hud.chips[0].classList.toggle('on', !!sc.rfid); P.hud.chips[1].classList.toggle('on', !!sc.visao); P.hud.chips[2].classList.toggle('on', !!sc.smartstock);
      P.last = {}; P.dirty = true; dirtyAll = true;
    };
    P.theme = function () {
      scene.background = new THREE.Color(css('--scene-bg') || '#0e1316');
      P.mats.slab.color.set(css('--floor') || '#2a343a'); P.mats.lane.color.set(css('--lane') || '#35424a');
      P.mats.yard.color.set(css('--yard') || '#20282c'); P.dirty = true; dirtyAll = true;
    };
    P.setScenario(idx); P.theme();
    return P;
  }

  /* ---------------------------------------------------- quadro por tempo */
  function renderPane(P, t, speed) {
    var sc = SC[P.idx], p = prep(sc), d = sc.dia, i, j;
    /* estoque físico x sistema no instante t */
    P.phys.set(d.phys0); P.sys.set(d.sys0);
    var nd = ub(p.deltaT, t);
    for (j = 0; j < nd; j++) { var dl = p.delta[j]; P.phys[dl[1]] += dl[2]; P.sys[dl[1]] += dl[3]; }
    var mis = P.mis0; for (i = 0; i < mis.length; i++) mis[i] = d.mis0[i];
    var nm = ub(p.misT, t);
    for (j = 0; j < nm; j++) mis[p.mis[j][1]] = p.mis[j][2];
    var diverg = 0, valor = 0;
    for (i = 0; i < P.phys.length; i++) {
      var it = LAY.itens[i], ph = P.phys[i], r = ph / Math.max(it.max, 1);
      var h = ph <= 0 ? 0.04 : 0.1 + 0.8 * clamp(r, 0, 1);
      var b = P.box[i], ps = itemPos[i];
      b.scale.y = h; b.position.y = ps.nivel * ALT + 0.06 + h / 2;
      var col = ph <= 0 ? '#7d8a92' : (r < 0.25 ? '#e5533d' : (r < 0.5 ? '#e0b252' : '#3fae6a'));
      if (P.last[i] !== col) { b.material.color.set(col); P.last[i] = col; }
      var df = P.sys[i] !== ph, mk = P.mk[i];
      mk.visible = df || mis[i] === 1;
      if (mk.visible) mk.material.color.set(mis[i] === 1 ? '#a855f7' : '#ff9f1c');
      if (df) diverg++;
      valor += ph * it.custo;
    }
    /* operadores */
    var acts = [];
    for (i = 0; i < P.ops.length; i++) {
      var segs = d.segs[i], n = ub(p.segT[i], t) - 1;
      var x, z, act = 'livre';
      if (n < 0) { x = d.pos0[i][0]; z = d.pos0[i][1]; }
      else {
        var s = segs[n];
        if (t < s[1]) { var f = s[1] > s[0] ? (t - s[0]) / (s[1] - s[0]) : 1; x = s[2] + (s[4] - s[2]) * f; z = s[3] + (s[5] - s[3]) * f; act = s[6]; }
        else { x = s[4]; z = s[5]; }
      }
      var op = P.ops[i]; op.g.position.set(x, 0, z); op.mat.color.set(ACT[act][1]); acts.push(act);
    }
    /* efeitos */
    P.pulses.forEach(function (m) { m.visible = false; }); P.rings.forEach(function (m) { m.visible = false; }); P.beams.forEach(function (m) { m.visible = false; });
    var np = 0, nr = 0, nb = 0, maxLife = 1.9 * speed;
    var lo = lb(p.evtT, t - maxLife), hi = ub(p.evtT, t);
    for (j = lo; j < hi; j++) {
      var e = p.evts[j], sp = EFF[e.tipo]; if (!sp) continue;
      var age = (t - e.t) / speed; if (age > sp.life) continue;
      var u = age / sp.life, px, py, pz;
      if (sp.at === 'item') { var q = itemPos[e.item]; px = q.pos[0]; py = q.nivel * ALT + 0.5; pz = q.pos[2]; }
      else if (sp.at === 'rec') { px = LAY.recebimento[0]; py = 1.2; pz = LAY.recebimento[1]; }
      else if (sp.at === 'exp') { px = LAY.expedicao[0]; py = 1.2; pz = LAY.expedicao[1]; }
      else { px = P.boardPos[0]; py = P.boardPos[1]; pz = P.boardPos[2]; }
      if (sp.k === 'pulse' || sp.pulse) {
        if (np < P.pulses.length) { var m = P.pulses[np++]; m.visible = true; m.position.set(px, py, pz); var sc2 = (sp.s || 0.8) * (0.3 + u * 1.1); m.scale.set(sc2, sc2, sc2); m.material.color.set(sp.pulse || sp.c); m.material.opacity = 0.75 * (1 - u); }
      }
      if (sp.k === 'ring' && nr < P.rings.length) { var rr = P.rings[nr++]; rr.visible = true; rr.position.set(px, py, pz); var s3 = 0.4 + u * 3.2; rr.scale.set(s3, s3, s3); rr.material.color.set(sp.c); rr.material.opacity = 0.9 * (1 - u); }
      if (sp.k === 'beam' && nb < P.beams.length && P.cams.length) {
        var best = P.cams[0], bd = 1e9;
        P.cams.forEach(function (c) { var dd = Math.abs(c[0] - px); if (dd < bd) { bd = dd; best = c; } });
        var ln = P.beams[nb++]; ln.visible = true; var pa = ln.geometry.attributes.position;
        pa.setXYZ(0, best[0], best[1], best[2] - 0.1); pa.setXYZ(1, px, py, pz); pa.needsUpdate = true;
        ln.material.color.set(sp.c); ln.material.opacity = 1 - u * 0.8;
      }
    }
    /* caminhões */
    var arr = ub(p.times.caminhao || [], t), sai = ub(p.times.caminhao_sai || [], t), ativos = clamp(arr - sai, 0, 3);
    for (i = 0; i < P.trucks.length; i++) P.trucks[i].visible = i < ativos;
    /* painel numérico */
    var C = function (k) { return p.times[k] ? ub(p.times[k], t) : 0; };
    var comp = C('pedido_ok'), cheg = C('pedido_chega'), fal = C('pedido_falha');
    var comp2 = C('pedido_compra');
    var html = '<div><span>Pedidos concluídos</span><b>' + comp + '/' + cheg + '</b></div>' +
      '<div><span>Falhas no pedido</span><b>' + fal + '</b></div>' +
      '<div><span>Rupturas</span><b>' + C('ruptura') + '</b></div>' +
      '<div><span>Estoque ≠ sistema</span><b>' + nf(100 * diverg / P.phys.length, 0) + '%</b></div>' +
      '<div><span>Alertas falsos</span><b>' + C('alerta_falso') + '</b></div>' +
      '<div><span>Pedidos de compra</span><b>' + comp2 + '</b></div>';
    if (P.last.k !== html) { P.hud.k.innerHTML = html; P.last.k = html; }
    var oh = acts.map(function (a, k2) { return '<div><i style="background:' + ACT[a][1] + '"></i>Op ' + (k2 + 1) + ' · ' + ACT[a][0] + '</div>'; }).join('');
    if (P.last.o !== oh) { P.hud.o.innerHTML = oh; P.last.o = oh; }
    P.renderer.render(P.scene, P.camera);
    P.dirty = false;
  }

  /* --------------------------------------------------- indicadores (tabela) */
  var G1 = 'Eficiência operacional (principal)', G2 = 'Nível de serviço', G3 = 'Acurácia do inventário', G4 = 'Estoque e reposição', G5 = 'Dados e sistema', G6 = 'Custo';
  var IND = [
    ['sep_tempo', G1, 'Tempo de separação por pedido', 'min', 'Menor', 3], ['prod', G1, 'Produtividade', 'pedidos/h', 'Maior', 3],
    ['ciclo', G1, 'Tempo de ciclo do pedido', 'h', 'Menor', 2], ['dist', G1, 'Distância percorrida por pedido', 'm', 'Menor', 1],
    ['busca', G1, 'Tempo procurando itens', 'min/dia', 'Menor', 1], ['receb', G1, 'Tempo de recebimento por lote', 'min', 'Menor', 2],
    ['contagem', G1, 'Tempo de contagem cíclica', 'h/mês', 'Menor', 2], ['erro_sep', G1, 'Erro de separação', '% pedidos', 'Menor', 2],
    ['retrab', G1, 'Retrabalho', '% pedidos', 'Menor', 1], ['util', G1, 'Utilização dos operadores', '% tempo', 'Informativo', null],
    ['fill', G2, 'Nível de serviço (fill rate)', '% demanda', 'Maior', null], ['otif', G2, 'Pedidos completos e no prazo', '% pedidos', 'Maior', null],
    ['rup_dias', G2, 'Dias de ruptura (por ano)', 'dias', 'Menor', null], ['rup_itens', G2, 'Itens com ruptura', '% itens', 'Menor', null],
    ['diverg', G3, 'Divergência de inventário', '% itens', 'Menor', null], ['acur_loc', G3, 'Acurácia de localização', '% itens', 'Maior', null],
    ['fantasma', G3, 'Estoque fantasma', 'R$', 'Menor', null], ['perdas', G3, 'Perdas e extravios (por ano)', 'R$', 'Menor', null],
    ['est_medio', G4, 'Estoque médio', 'R$', 'Menor', null], ['giro', G4, 'Giro anual', 'vezes/ano', 'Maior', null],
    ['cobertura', G4, 'Cobertura de estoque', 'dias', 'Informativo', null], ['ped_compra', G4, 'Pedidos de compra (por ano)', 'pedidos', 'Menor', null],
    ['emergencia', G4, 'Compras emergenciais (por ano)', 'pedidos', 'Menor', null], ['ocupacao', G4, 'Ocupação do espaço', '% posições', 'Informativo', null],
    ['latencia', G5, 'Latência da informação', 'min', 'Menor', null], ['rastreio', G5, 'Movimentos rastreados', '% mov.', 'Maior', null],
    ['falsos', G5, 'Alertas falsos', 'por semana', 'Menor', null]
  ];
  function isPct(u) { return u.charAt(0) === '%'; }
  function fmtV(u, v) {
    if (isPct(u)) return nf(v * 100, 1) + '%';
    if (u === 'R$') return 'R$ ' + nf(v, 0);
    return nf(v, Math.abs(v) >= 100 ? 0 : (Math.abs(v) >= 10 ? 1 : 2));
  }
  function effIndex(ref, sel) {
    var num = 0, den = 0;
    IND.forEach(function (x) {
      if (x[5] === null) return;
      var r = ref[x[0]], v = sel[x[0]], s;
      if (x[4] === 'Menor') s = v <= 0 ? (r <= 0 ? 1 : 2) : Math.min(2, r / v);
      else s = r <= 0 ? 0 : Math.min(2, v / r);
      if (s === 0) return;
      num += x[5] * s; den += x[5];
    });
    return den ? 100 * num / den : null;
  }
  function deltaCell(better, r, v) {
    if (!isFinite(r) || r === 0) return '<td class="dl">—</td>';
    var d = (v - r) / Math.abs(r);
    if (Math.abs(d) < 0.0005) return '<td class="dl">0%</td>';
    var cls = better === 'Informativo' ? '' : ((d < 0) === (better === 'Menor') ? 'good' : 'bad');
    return '<td class="dl ' + cls + '">' + (d > 0 ? '+' : '−') + nf(Math.abs(d) * 100, 0) + '%</td>';
  }
  function techCost(sc) {
    return { anual: sc.rfid * TEC.rfid.anual + sc.visao * TEC.visao.anual + sc.smartstock * TEC.smartstock.anual,
      invest: sc.rfid * TEC.rfid.invest + sc.visao * TEC.visao.invest + sc.smartstock * TEC.smartstock.invest };
  }
  function renderCompare(iRef, iSel) {
    var A = SC[iRef], B = SC[iSel], a = A.kpis, b = B.kpis;
    var ei = effIndex(a, b);
    $('#ref-name').textContent = A.nome; $('#sel-name').textContent = B.nome;
    var same = iRef === iSel;
    $('#eff-val').textContent = ei === null ? '—' : nf(ei, 0);
    $('#eff-sub').textContent = same ? 'Os dois cenários são o mesmo. Escolha outro para comparar.' : 'pontos, com ' + A.nome + ' = 100';
    var rows = '', g = '';
    IND.forEach(function (x) {
      if (x[1] !== g) { g = x[1]; rows += '<tr class="grp' + (g === G1 ? ' main' : '') + '"><th colspan="5">' + g + '</th></tr>'; }
      rows += '<tr><th scope="row">' + x[2] + (x[5] !== null ? ' <em>peso ' + x[5] + '</em>' : '') + '</th><td class="un">' + x[3] + '</td><td class="nm">' + fmtV(x[3], a[x[0]]) + '</td><td class="nm">' + fmtV(x[3], b[x[0]]) + '</td>' + deltaCell(x[4], a[x[0]], b[x[0]]) + '</tr>';
    });
    $('#kpi-body').innerHTML = rows;

    var ca = A.componentes, cb = B.componentes, ta = techCost(A), tb = techCost(B);
    var parts = [['mao_de_obra', 'Mão de obra', '--c1'], ['posse', 'Posse de estoque', '--c2'], ['pedidos', 'Pedidos de compra', '--c3'], ['ruptura', 'Ruptura', '--c4'], ['perdas', 'Perdas', '--c5'], ['tec', 'Tecnologias', '--c6']];
    function bar(c, t, name) {
      var all = Object.assign({}, c, { tec: t.anual }), tot = 0; Object.keys(all).forEach(function (k) { tot += all[k]; });
      var mx = Math.max(a.custo_op + ta.anual, b.custo_op + tb.anual);
      var w = tot / mx * 100;
      var seg = parts.map(function (pp) { var v = all[pp[0]] || 0; return '<span style="width:' + (v / tot * 100) + '%;background:var(' + pp[2] + ')" title="' + pp[1] + ': R$ ' + nf(v, 0) + '"></span>'; }).join('');
      return '<div class="brow"><div class="bname">' + name + '</div><div class="btrack"><div class="bfill" style="width:' + w + '%">' + seg + '</div></div><div class="btot nm">R$ ' + nf(tot, 0) + '</div></div>';
    }
    $('#cost-bars').innerHTML = bar(ca, ta, A.nome) + bar(cb, tb, B.nome) +
      '<div class="legendline">' + parts.map(function (pp) { return '<span><i style="background:var(' + pp[2] + ')"></i>' + pp[1] + '</span>'; }).join('') + '</div>';
    var tA = a.custo_op + ta.anual, tB = b.custo_op + tb.anual, eco = tA - tB, inv = tb.invest - ta.invest;
    var sumTxt;
    if (same) sumTxt = 'Escolha outro cenário para ver economia, retorno e prazo de pagamento.';
    else {
      var roi = inv > 0 ? eco / inv : null, pay = inv > 0 && eco > 0 ? inv / eco * 12 : null;
      sumTxt = '<b class="' + (eco >= 0 ? 'good' : 'bad') + '">' + (eco >= 0 ? 'Economia' : 'Custo extra') + ' de R$ ' + nf(Math.abs(eco), 0) + ' por ano</b> em relação a ' + A.nome + '.' +
        (inv > 0 ? ' Investimento adicional: R$ ' + nf(inv, 0) + (pay !== null ? '; retorno em ' + nf(pay, 0) + ' meses.' : '; sem retorno nas premissas atuais.') : '');
    }
    $('#cost-sum').innerHTML = sumTxt;
    drawCharts(A, B);
  }

  /* ------------------------------------------------------------ gráficos */
  function down(arr, n) {
    if (arr.length <= n) return arr.slice();
    var out = [], step = arr.length / n;
    for (var i = 0; i < n; i++) { var s = Math.floor(i * step), e = Math.floor((i + 1) * step), t = 0, c = 0; for (var j = s; j < Math.max(e, s + 1); j++) { t += arr[j]; c++; } out.push(t / c); }
    return out;
  }
  function chart(el, sa, sb, fmt) {
    var W = 560, H = 190, L = 76, R = 12, T = 12, B = 24;
    var a = down(sa, 120), b = down(sb, 120), mx = 0;
    a.concat(b).forEach(function (v) { mx = Math.max(mx, v); });
    mx = mx || 1; var top = mx * 1.08;
    function X(i) { return L + (W - L - R) * i / (a.length - 1); }
    function Y(v) { return T + (H - T - B) * (1 - v / top); }
    var s = '';
    [0, 0.5, 1].forEach(function (f) {
      var v = top / 1.08 * f, y = Y(v);
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" class="gl"/><text x="' + (L - 6) + '" y="' + (y + 3.5) + '" text-anchor="end" class="ax">' + fmt(v) + '</text>';
    });
    var days = sa.length;
    [0, 0.25, 0.5, 0.75, 1].forEach(function (f) {
      s += '<text x="' + (L + (W - L - R) * f) + '" y="' + (H - 6) + '" text-anchor="' + (f === 0 ? 'start' : (f === 1 ? 'end' : 'middle')) + '" class="ax">dia ' + Math.round(f * (days - 1)) + '</text>';
    });
    function path(v, cls) { return '<polyline class="' + cls + '" points="' + v.map(function (y, i) { return X(i).toFixed(1) + ',' + Y(y).toFixed(1); }).join(' ') + '"/>'; }
    s += path(a, 'lref') + path(b, 'lsel');
    s += '<circle cx="' + X(a.length - 1) + '" cy="' + Y(a[a.length - 1]) + '" r="3.4" class="dref"/><circle cx="' + X(b.length - 1) + '" cy="' + Y(b[b.length - 1]) + '" r="3.4" class="dsel"/>';
    el.setAttribute('viewBox', '0 0 ' + W + ' ' + H); el.innerHTML = s;
  }
  function drawCharts(A, B) {
    chart($('#ch-div'), A.series.divergencia, B.series.divergencia, function (v) { return nf(v * 100, 0) + '%'; });
    chart($('#ch-est'), A.series.estoque_valor, B.series.estoque_valor, function (v) { return 'R$ ' + nf(v / 1000, 0) + ' mil'; });
    $$('.lg-ref').forEach(function (e) { e.textContent = A.nome; }); $$('.lg-sel').forEach(function (e) { e.textContent = B.nome; });
  }

  /* ----------------------------------------------------------- inicialização */
  var iRef = 0, iSel = findSc(1, 1, 1);
  panes.push(makePane($('#pane-ref'), iRef)); panes.push(makePane($('#pane-sel'), iSel));
  var selRef = $('#sel-ref-s'), selSel = $('#sel-sel-s');
  SC.forEach(function (sc, i) {
    [selRef, selSel].forEach(function (s) { var o = document.createElement('option'); o.value = i; o.textContent = sc.nome; s.appendChild(o); });
  });
  var sw = { rfid: $('#sw-rfid'), visao: $('#sw-visao'), smart: $('#sw-smart') };
  function syncUI() {
    selRef.value = iRef; selSel.value = iSel;
    var c = SC[iSel];
    sw.rfid.setAttribute('aria-checked', c.rfid ? 'true' : 'false'); sw.visao.setAttribute('aria-checked', c.visao ? 'true' : 'false'); sw.smart.setAttribute('aria-checked', c.smartstock ? 'true' : 'false');
    panes[0].setScenario(iRef); panes[1].setScenario(iSel);
    $$('.ptitle').forEach(function (e, k) { e.textContent = SC[k ? iSel : iRef].nome; });
    renderCompare(iRef, iSel);
  }
  function flip(k) { return function () { var c = SC[iSel], r = c.rfid, v = c.visao, s = c.smartstock; if (k === 'rfid') r = 1 - r; if (k === 'visao') v = 1 - v; if (k === 'smart') s = 1 - s; iSel = findSc(r, v, s); syncUI(); }; }
  sw.rfid.addEventListener('click', flip('rfid')); sw.visao.addEventListener('click', flip('visao')); sw.smart.addEventListener('click', flip('smart'));
  selRef.addEventListener('change', function () { iRef = +selRef.value; syncUI(); });
  selSel.addEventListener('change', function () { iSel = +selSel.value; syncUI(); });
  $('#cam-sync').addEventListener('change', function (e) { syncCam = e.target.checked; });
  $('#cam-reset').addEventListener('click', function () {
    panes.forEach(function (P) { P.camera.position.set(LAY.largura * 0.5, Math.max(LAY.largura, LAY.profundidade) * 0.92, LAY.profundidade + Math.max(LAY.largura, LAY.profundidade) * 0.2); P.controls.target.set(LAY.largura * 0.5, 0, LAY.profundidade * 0.46); P.controls.update(); P.dirty = true; });
    dirtyAll = true;
  });

  /* relógio */
  var t = T0 + 3600, playing = !(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches), speed = 120, lastNow = performance.now();
  var slider = $('#t-slider'), clock = $('#t-clock'), playBtn = $('#t-play'), spd = $('#t-speed');
  slider.min = T0; slider.max = Math.ceil(TMAX); slider.value = t;
  function setPlay(v) { playing = v; playBtn.textContent = v ? 'Pausar' : (t >= TMAX - 1 ? 'Repetir' : 'Reproduzir'); playBtn.setAttribute('aria-pressed', v ? 'true' : 'false'); }
  playBtn.addEventListener('click', function () { if (!playing && t >= TMAX - 1) t = T0; setPlay(!playing); dirtyAll = true; });
  spd.addEventListener('change', function () { speed = +spd.value; dirtyAll = true; });
  slider.addEventListener('input', function () { t = +slider.value; dirtyAll = true; setPlay(false); });
  spd.value = String(speed);
  setPlay(playing);

  function frame(now) {
    var dt = Math.min(0.25, (now - lastNow) / 1000); lastNow = now;
    if (playing) {
      t += dt * speed;
      if (t >= TMAX) { t = TMAX; setPlay(false); }
      slider.value = t; dirtyAll = true;
    }
    if (dirtyAll) {
      clock.textContent = hms(t);
      panes.forEach(function (P) { renderPane(P, t, speed); });
      dirtyAll = false;
    }
    requestAnimationFrame(frame);
  }
  function applyTheme() { panes.forEach(function (P) { P.theme(); }); drawCharts(SC[iRef], SC[iSel]); }
  if (window.matchMedia) { var mq = matchMedia('(prefers-color-scheme: dark)'); (mq.addEventListener ? mq.addEventListener('change', applyTheme) : mq.addListener(applyTheme)); }
  new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  $('#meta-line').textContent = META.n_itens + ' itens, ' + META.n_operadores + ' operadores, ' + META.dias + ' dias simulados. Dia reproduzido: dia ' + META.dia_viz + '.';
  $('#aviso').textContent = META.aviso;
  syncUI(); applyTheme();
  window.__almox = { panes: panes, setT: function (v) { t = v; slider.value = v; dirtyAll = true; setPlay(false); }, set: function (r, s) { iRef = r; iSel = s; syncUI(); } };
  requestAnimationFrame(function (n) { lastNow = n; frame(n); });
})();
