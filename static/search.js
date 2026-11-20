/* 作品検索（外部ライブラリなし）。JSが無ければフォームは /work/ に移動する。 */
(function () {
  var input = document.getElementById("q");
  var list = document.getElementById("sr");
  if (!input || !list) return;
  var data = null, loading = false;
  function fold(s) {
    s = String(s).normalize("NFKC").toLowerCase();
    return s.replace(/[ァ-ヶ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0x60); }).replace(/\s+/g, "");
  }
  function load(cb) {
    if (data) return cb();
    if (loading) return;
    loading = true;
    fetch("/static/search.json").then(function (r) { return r.json(); }).then(function (j) {
      data = j.map(function (x) { x.k = fold(x.t + " " + x.a); return x; });
      cb();
    }).catch(function () { loading = false; });
  }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function render() {
    var q = fold(input.value);
    if (!q || !data) { list.hidden = true; list.innerHTML = ""; return; }
    var out = [];
    for (var i = 0; i < data.length && out.length < 12; i++) {
      if (data[i].k.indexOf(q) !== -1) out.push(data[i]);
    }
    list.innerHTML = out.length ? out.map(function (x) {
      return '<li><a href="/work/' + x.s + '/">' + esc(x.t) + '</a><small>' + esc(x.a) + "　" + esc(x.p) +
        "　最新: " + esc(x.v) + "（" + x.d + "）</small></li>";
    }).join("") : '<li class="none">見つかりません</li>';
    list.hidden = false;
  }
  input.addEventListener("input", function () { load(render); });
  input.addEventListener("focus", function () { load(function () {}); });
  input.form.addEventListener("submit", function (e) {
    if (data && input.value.trim()) { e.preventDefault(); render(); }
  });
  document.addEventListener("click", function (e) { if (!e.target.closest(".search")) list.hidden = true; });
})();
