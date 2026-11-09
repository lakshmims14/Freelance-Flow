/*
  FreelanceFlow charts: one small column chart, no libraries, works offline.

  How to use it in a template:
      {{ chart_data|json_script:"billed-data" }}
      <div class="ff-chart" data-ff-columns data-source="billed-data"
           data-value-name="Billed" data-color="#7C6CFF" data-hover="#9488FF"></div>

  chart_data is a list like:  [{"label": "May", "full": "May 2026", "value": 141600, "note": "3 invoices"}, ...]

  Draws: hairline gridlines, thin columns with rounded tops, the biggest value labelled on its column,
  a hover/keyboard tooltip, and a "View as table" list under the chart so nothing depends on hovering.
*/
(function () {
  var SVG = 'http://www.w3.org/2000/svg';

  function node(name, attrs, parent) {
    var n = document.createElementNS(SVG, name);
    for (var k in attrs) { n.setAttribute(k, attrs[k]); }
    if (parent) { parent.appendChild(n); }
    return n;
  }

  function trim(x) { return (Math.round(x * 10) / 10).toString(); }

  // Axis labels: ₹500, ₹2K, ₹1.5L, ₹2Cr  (lakh / crore, the way Indian invoices are read)
  function compact(n) {
    var a = Math.abs(n);
    if (a >= 1e7) { return '₹' + trim(n / 1e7) + 'Cr'; }
    if (a >= 1e5) { return '₹' + trim(n / 1e5) + 'L'; }
    if (a >= 1e3) { return '₹' + trim(n / 1e3) + 'K'; }
    return '₹' + Math.round(n);
  }

  function full(n) {
    return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  // A tidy top value for the axis: 1, 2, 2.5, 5 or 10 times a power of ten, in 4 steps
  function niceStep(max) {
    var raw = max / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), best = mag;
    [1, 2, 2.5, 5, 10].some(function (m) { best = m * mag; return best >= raw; });
    return best;
  }

  function barPath(x, y, w, h, r) {
    r = Math.min(r, h, w / 2);
    return 'M' + x + ' ' + (y + h) + 'V' + (y + r) + 'A' + r + ' ' + r + ' 0 0 1 ' + (x + r) + ' ' + y +
           'H' + (x + w - r) + 'A' + r + ' ' + r + ' 0 0 1 ' + (x + w) + ' ' + (y + r) + 'V' + (y + h) + 'Z';
  }

  function draw(box, data, opt) {
    box.textContent = '';
    var W = box.clientWidth, H = box.clientHeight;
    if (!W || !H || !data.length) { return; }

    var m = { l: 46, r: 8, t: 22, b: 26 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var maxV = Math.max.apply(null, data.map(function (d) { return d.value; }));
    var step = niceStep(maxV || 1), top = step * 4;
    var y = function (v) { return m.t + ih - (v / top) * ih; };

    var svg = node('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'group', 'aria-label': opt.name + ' by month' }, box);

    // gridlines + y labels (solid hairlines, one style)
    for (var i = 0; i <= 4; i++) {
      var gy = y(step * i);
      node('line', { x1: m.l, x2: W - m.r, y1: gy, y2: gy, 'class': 'grid' }, svg);
      var t = node('text', { x: m.l - 8, y: gy + 4, 'text-anchor': 'end', 'class': 'tick' }, svg);
      t.textContent = compact(step * i);
    }

    var tip = document.createElement('div');
    tip.className = 'ff-tip';
    var tv = document.createElement('div'); tv.className = 'v';
    var tk = document.createElement('div'); tk.className = 'k';
    var tn = document.createElement('div'); tn.className = 'k';
    tip.appendChild(tv); tip.appendChild(tk); tip.appendChild(tn);
    box.appendChild(tip);

    var band = iw / data.length, bw = Math.min(24, band * 0.5);
    var peak = data.indexOf(data.filter(function (d) { return d.value === maxV; })[0]);

    function show(i, bar) {
      var d = data[i];
      tv.textContent = '';
      var key = document.createElement('span'); key.className = 'key'; key.style.background = opt.color;
      tv.appendChild(key); tv.appendChild(document.createTextNode(full(d.value)));
      tk.textContent = d.full || d.label;
      tn.textContent = d.note || '';
      tn.style.display = d.note ? '' : 'none';
      var cx = m.l + band * i + band / 2;
      tip.style.top = (y(d.value) - 10) + 'px';
      tip.classList.add('show');
      var half = tip.offsetWidth / 2;
      tip.style.left = Math.max(half, Math.min(W - half, cx)) + 'px';
      if (bar) { bar.setAttribute('fill', opt.hover); }
    }
    function hide(bar) { tip.classList.remove('show'); if (bar) { bar.setAttribute('fill', opt.color); } }

    data.forEach(function (d, i) {
      var cx = m.l + band * i + band / 2;
      var h = (d.value / top) * ih, bar = null;
      if (d.value > 0) {
        bar = node('path', { d: barPath(cx - bw / 2, y(d.value), bw, h, 4), fill: opt.color, 'class': 'bar' }, svg);
      }
      var lab = node('text', { x: cx, y: H - 8, 'text-anchor': 'middle', 'class': 'tick' }, svg);
      lab.textContent = d.label;
      if (i === peak && d.value > 0) {
        var p = node('text', { x: cx, y: y(d.value) - 7, 'class': 'peak' }, svg);
        p.textContent = compact(d.value);
      }
      // the hover target is the whole column slot, much bigger than the thin bar
      var hit = node('rect', { x: m.l + band * i, y: m.t, width: band, height: ih + 2, 'class': 'hit', tabindex: 0,
                               role: 'img', 'aria-label': (d.full || d.label) + ': ' + full(d.value) + (d.note ? ', ' + d.note : '') }, svg);
      hit.addEventListener('pointerenter', function () { show(i, bar); });
      hit.addEventListener('pointermove', function () { show(i, bar); });
      hit.addEventListener('pointerleave', function () { hide(bar); });
      hit.addEventListener('focus', function () { show(i, bar); });
      hit.addEventListener('blur', function () { hide(bar); });
    });
  }

  function addTable(box, data, opt) {
    var details = document.createElement('details');
    details.className = 'ff-chart-table';
    var sum = document.createElement('summary');
    sum.textContent = 'View as table';
    details.appendChild(sum);
    var table = document.createElement('table');
    table.className = 'table table-sm';
    var head = table.createTHead().insertRow();
    ['Month', opt.name, 'Detail'].forEach(function (h) {
      var th = document.createElement('th'); th.textContent = h; head.appendChild(th);
    });
    var body = table.createTBody();
    data.forEach(function (d) {
      var r = body.insertRow();
      r.insertCell().textContent = d.full || d.label;
      var c = r.insertCell(); c.textContent = full(d.value); c.className = 'num';
      r.insertCell().textContent = d.note || '';
    });
    details.appendChild(table);
    box.insertAdjacentElement('afterend', details);
  }

  function init(box) {
    var src = document.getElementById(box.getAttribute('data-source'));
    if (!src) { return; }
    var data = JSON.parse(src.textContent);
    var opt = {
      name: box.getAttribute('data-value-name') || 'Amount',
      color: box.getAttribute('data-color') || '#7C6CFF',
      hover: box.getAttribute('data-hover') || '#9488FF'
    };
    addTable(box, data, opt);
    var queued = false;
    function again() {
      if (queued) { return; }
      queued = true;
      requestAnimationFrame(function () { queued = false; draw(box, data, opt); });
    }
    again();
    if (window.ResizeObserver) { new ResizeObserver(again).observe(box); }
    else { window.addEventListener('resize', again); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(document.querySelectorAll('[data-ff-columns]'), init);
  });
})();
