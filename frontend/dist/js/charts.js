/* 激浪 · 轻量图表（内联 SVG，零第三方依赖）
 *
 * 前端是无构建原生工程，引 Recharts 就得加 Vite 构建链并改掉
 * Render 单服务托管形态。这里只实现页面上真正用到的两种图形：
 * 面积折线（业绩走势）和柱状（时段分布），带悬停十字线与浮层。
 *
 * 用法：CPChart.line(hostEl, { series, format }) / CPChart.bars(hostEl, {...})
 * hostEl 需要是已插入文档的容器——宽度按容器实测值算，窗口变化会重绘。
 */
(function () {
  "use strict";

  const COLOR = {
    text: "#73737B",
    textSoft: "#A1A1AA",
    grid: "#EFEFF2",
    line: "#1B6EF3",
    bar: "#93BBFB",
    barHover: "#1B6EF3",
  };

  function themeColor(name, fallback) {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim();
    return value || fallback;
  }

  /* ---------------- 数值格式化 ---------------- */

  function currencySymbol(code) {
    const map = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥" };
    return map[String(code || "USD").toUpperCase()] || "";
  }

  function money(value, code) {
    const n = Number(value) || 0;
    const unit = currencySymbol(code);
    if (Math.abs(n) >= 1000000) return unit + (n / 1000000).toFixed(1) + "M";
    if (Math.abs(n) >= 1000) return unit + (n / 1000).toFixed(1) + "k";
    return unit + n.toFixed(n >= 100 ? 0 : 2);
  }

  function num(value) {
    const n = Number(value) || 0;
    if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (Math.abs(n) >= 10000) return (n / 1000).toFixed(1) + "k";
    return n.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
  }

  function pct(value) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    return n.toFixed(2) + "%";
  }

  function moneyFull(value, code) {
    const n = Number(value) || 0;
    return currencySymbol(code) + n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  const FORMATTER = { money: money, currency: money, number: num, percent: pct, ratio: num };

  function format(value, kind, code) {
    const fn = FORMATTER[kind] || num;
    return fn(value, code);
  }

  function shortDate(value) {
    const text = String(value || "");
    return text.length >= 10 ? text.slice(5) : text;
  }

  /* ---------------- 浮层 ---------------- */

  function ensureTip(host) {
    let tip = host.querySelector(".cp-chart-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "cp-chart-tip";
      tip.hidden = true;
      host.appendChild(tip);
    }
    return tip;
  }

  function showTip(host, tip, x, y, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    const hostBox = host.getBoundingClientRect();
    let left = x - box.width / 2;
    left = Math.max(4, Math.min(left, hostBox.width - box.width - 4));
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, y - box.height - 10) + "px";
  }

  /* ---------------- 面积折线 ---------------- */

  function line(host, spec) {
    if (!host) return;
    const series = (spec && spec.series) || [];
    const currency = spec && spec.currency;
    const kind = (spec && spec.format) || "number";
    host.innerHTML = "";
    host.classList.add("cp-chart");

    if (!series.length) {
      host.innerHTML = '<div class="cp-chart-empty">这个时间范围内没有数据</div>';
      return;
    }

    const width = Math.max(240, host.clientWidth || 640);
    const height = spec.height || 232;
    const padL = Math.max(38, Math.round(width * 0.07));
    const padR = 10;
    const padT = 12;
    const padB = 24;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;

    const values = series.map(function (d) { return Number(d.value) || 0; });
    const max = Math.max.apply(null, values.concat([1]));
    const stepX = series.length > 1 ? innerW / (series.length - 1) : 0;

    const points = series.map(function (d, i) {
      const ratio = (Number(d.value) || 0) / max;
      return {
        x: padL + stepX * i,
        y: padT + innerH - ratio * innerH,
        value: Number(d.value) || 0,
        label: d.date,
      };
    });

    const path = points.map(function (p, i) {
      return (i ? "L" : "M") + p.x.toFixed(1) + "," + p.y.toFixed(1);
    }).join(" ");
    const area = path +
      " L" + points[points.length - 1].x.toFixed(1) + "," + (padT + innerH).toFixed(1) +
      " L" + points[0].x.toFixed(1) + "," + (padT + innerH).toFixed(1) + " Z";

    const grid = [0, 0.5, 1].map(function (ratio) {
      const y = padT + innerH - ratio * innerH;
      return '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (width - padR).toFixed(1) +
        '" y2="' + y.toFixed(1) + '" stroke="' + COLOR.grid + '" stroke-width="1" />' +
        '<text x="' + (padL - 8) + '" y="' + (y + 3.5).toFixed(1) +
        '" text-anchor="end" font-size="10" fill="' + COLOR.textSoft + '">' +
        format(max * ratio, kind, currency) + "</text>";
    }).join("");

    const tickCount = Math.min(6, series.length);
    const ticks = [];
    for (let i = 0; i < tickCount; i += 1) {
      const index = Math.round((series.length - 1) * (i / Math.max(1, tickCount - 1)));
      const point = points[index];
      if (!point) continue;
      ticks.push(
        '<text x="' + point.x.toFixed(1) + '" y="' + (height - 8) +
        '" text-anchor="middle" font-size="10" fill="' + COLOR.textSoft + '">' +
        shortDate(point.label) + "</text>"
      );
    }

    const svg =
      '<svg class="cp-chart-svg" viewBox="0 0 ' + width + " " + height +
      '" width="100%" height="' + height + '" role="img" aria-label="' +
      (spec.label || "走势图") + '">' +
      grid + ticks +
      '<path d="' + area + '" fill="' + themeColor("--primary", COLOR.line) + '" fill-opacity="0.07" />' +
      '<path d="' + path + '" fill="none" stroke="' + themeColor("--primary", COLOR.line) +
      '" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />' +
      '<line class="cp-chart-guide" x1="0" y1="' + padT + '" x2="0" y2="' + (padT + innerH) +
      '" stroke="' + themeColor("--primary", COLOR.line) +
      '" stroke-width="1" stroke-dasharray="3 3" opacity="0" />' +
      '<circle class="cp-chart-dot" r="3.4" fill="#fff" stroke="' +
      themeColor("--primary", COLOR.line) + '" stroke-width="2" opacity="0" />' +
      "</svg>";
    host.insertAdjacentHTML("beforeend", svg);

    const svgEl = host.querySelector("svg");
    const guide = host.querySelector(".cp-chart-guide");
    const dot = host.querySelector(".cp-chart-dot");
    const tip = ensureTip(host);

    function move(event) {
      const box = svgEl.getBoundingClientRect();
      const scale = width / (box.width || width);
      const x = (event.clientX - box.left) * scale;
      let best = 0;
      let bestDistance = Infinity;
      points.forEach(function (p, i) {
        const distance = Math.abs(p.x - x);
        if (distance < bestDistance) { bestDistance = distance; best = i; }
      });
      const point = points[best];
      guide.setAttribute("x1", point.x);
      guide.setAttribute("x2", point.x);
      guide.setAttribute("opacity", "1");
      dot.setAttribute("cx", point.x);
      dot.setAttribute("cy", point.y);
      dot.setAttribute("opacity", "1");
      showTip(host, tip, point.x / scale, point.y / scale,
        '<span class="cp-chart-tip-label">' + (point.label || "") + "</span>" +
        '<span class="cp-chart-tip-value">' + format(point.value, kind, currency) + "</span>");
    }

    function leave() {
      guide.setAttribute("opacity", "0");
      dot.setAttribute("opacity", "0");
      tip.hidden = true;
    }

    svgEl.addEventListener("mousemove", move);
    svgEl.addEventListener("mouseleave", leave);

    bindResize(host, function () { line(host, spec); });
  }

  /* ---------------- 柱状 ---------------- */

  function bars(host, spec) {
    if (!host) return;
    const series = (spec && spec.series) || [];
    host.innerHTML = "";
    host.classList.add("cp-chart");

    if (!series.length) {
      host.innerHTML = '<div class="cp-chart-empty">这个时间范围内没有数据</div>';
      return;
    }

    const width = Math.max(240, host.clientWidth || 640);
    const height = spec.height || 168;
    const padL = 34;
    const padR = 10;
    const padT = 10;
    const padB = 22;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const values = series.map(function (d) { return Number(d.value) || 0; });
    const max = Math.max.apply(null, values.concat([1]));
    const slot = innerW / series.length;
    const barWidth = Math.max(3, Math.min(18, slot * 0.62));

    const grid = [0, 0.5, 1].map(function (ratio) {
      const y = padT + innerH - ratio * innerH;
      return '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (width - padR).toFixed(1) +
        '" y2="' + y.toFixed(1) + '" stroke="' + COLOR.grid + '" stroke-width="1" />' +
        '<text x="' + (padL - 8) + '" y="' + (y + 3.5).toFixed(1) +
        '" text-anchor="end" font-size="10" fill="' + COLOR.textSoft + '">' +
        Math.round(max * ratio) + "</text>";
    }).join("");

    const rects = series.map(function (d, i) {
      const value = Number(d.value) || 0;
      const barHeight = Math.max(value > 0 ? 2 : 0, (value / max) * innerH);
      const x = padL + slot * i + (slot - barWidth) / 2;
      const y = padT + innerH - barHeight;
      return '<rect class="cp-bar" data-i="' + i + '" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
        '" width="' + barWidth.toFixed(1) + '" height="' + barHeight.toFixed(1) +
        '" rx="2" fill="' + COLOR.bar + '" />';
    }).join("");

    const ticks = series.map(function (d, i) {
      const hour = Number(d.hour);
      if (isNaN(hour) || hour % 4 !== 0) return "";
      const x = padL + slot * i + slot / 2;
      return '<text x="' + x.toFixed(1) + '" y="' + (height - 6) +
        '" text-anchor="middle" font-size="10" fill="' + COLOR.textSoft + '">' +
        hour + "点</text>";
    }).join("");

    const svg =
      '<svg class="cp-chart-svg" viewBox="0 0 ' + width + " " + height +
      '" width="100%" height="' + height + '" role="img" aria-label="' +
      (spec.label || "分布图") + '">' + grid + rects + ticks + "</svg>";
    host.insertAdjacentHTML("beforeend", svg);

    const svgEl = host.querySelector("svg");
    const tip = ensureTip(host);

    svgEl.addEventListener("mousemove", function (event) {
      const target = event.target.closest(".cp-bar");
      if (!target) { tip.hidden = true; return; }
      const index = Number(target.getAttribute("data-i"));
      const item = series[index];
      if (!item) return;
      host.querySelectorAll(".cp-bar").forEach(function (bar) {
        bar.setAttribute("fill", bar === target ? COLOR.barHover : COLOR.bar);
      });
      const box = svgEl.getBoundingClientRect();
      const scale = width / (box.width || width);
      const rect = target.getBoundingClientRect();
      showTip(host, tip,
        (rect.left - box.left + rect.width / 2) / scale,
        rect.top - box.top,
        '<span class="cp-chart-tip-label">' + String(item.label || item.hour) + "</span>" +
        '<span class="cp-chart-tip-value">' + format(item.value, spec.format || "number") + "</span>");
    });

    svgEl.addEventListener("mouseleave", function () {
      tip.hidden = true;
      host.querySelectorAll(".cp-bar").forEach(function (bar) {
        bar.setAttribute("fill", COLOR.bar);
      });
    });

    bindResize(host, function () { bars(host, spec); });
  }

  /* ---------------- 尺寸变化重绘 ---------------- */

  const observed = new WeakMap();

  function bindResize(host, redraw) {
    if (typeof ResizeObserver !== "function") return;
    if (observed.has(host)) observed.get(host).disconnect();
    let lastWidth = host.clientWidth;
    let timer = null;
    const observer = new ResizeObserver(function () {
      const width = host.clientWidth;
      if (!width || Math.abs(width - lastWidth) < 12) return;
      lastWidth = width;
      clearTimeout(timer);
      timer = setTimeout(redraw, 120);
    });
    observer.observe(host);
    observed.set(host, observer);
  }

  window.CPChart = {
    line: line,
    bars: bars,
    money: money,
    moneyFull: moneyFull,
    num: num,
    pct: pct,
    format: format,
  };
})();
