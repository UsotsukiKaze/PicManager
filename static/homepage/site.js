(function () {
    "use strict";

    var pixelAnimationId = null;
    var pixelObserver = null;

    function renderPixelBanner(text) {
        var grid = document.getElementById("pixelGrid");
        if (!grid) return;

        if (pixelAnimationId) cancelAnimationFrame(pixelAnimationId);
        if (pixelObserver) pixelObserver.disconnect();

        var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        var containerWidth = grid.parentElement.clientWidth || 420;
        var gap = 1;
        var cellSize = containerWidth < 500 ? 4 : 5;
        var cols = Math.max(38, Math.min(70, Math.floor((containerWidth + gap) / (cellSize + gap))));
        var rows = containerWidth < 500 ? 14 : 16;

        var canvas = document.createElement("canvas");
        canvas.width = cols;
        canvas.height = rows;
        var context = canvas.getContext("2d");
        context.fillStyle = "#000";
        context.fillRect(0, 0, cols, rows);
        context.fillStyle = "#fff";
        context.font = "italic 100 " + (rows - 2) + 'px "Microsoft YaHei", "PingFang SC", sans-serif';
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(text, cols / 2, rows / 2);

        var data = context.getImageData(0, 0, cols, rows);
        var active = [];
        var fragment = document.createDocumentFragment();
        grid.replaceChildren();
        grid.style.display = "grid";
        grid.style.gridTemplateColumns = "repeat(" + cols + ", " + cellSize + "px)";
        grid.style.gap = gap + "px";

        for (var row = 0; row < rows; row += 1) {
            for (var column = 0; column < cols; column += 1) {
                var cell = document.createElement("span");
                cell.style.width = cellSize + "px";
                cell.style.height = cellSize + "px";
                cell.style.borderRadius = "1px";
                if (data.data[(row * cols + column) * 4] > 80) {
                    cell.className = "pixel-active";
                    active.push({ element: cell, column: column });
                } else {
                    cell.style.background = "rgba(255,255,255,0.09)";
                }
                fragment.appendChild(cell);
            }
        }
        grid.appendChild(fragment);

        if (reducedMotion) {
            active.forEach(function (pixel) {
                pixel.element.style.background = "hsl(205,80%,66%)";
            });
            return;
        }

        var offset = 0;
        function animate() {
            active.forEach(function (pixel) {
                var hue = ((pixel.column / cols) * 240 + offset) % 360;
                pixel.element.style.background = "hsl(" + hue + ",80%,66%)";
            });
            offset = (offset - 0.35 + 360) % 360;
            pixelAnimationId = requestAnimationFrame(animate);
        }

        pixelObserver = new IntersectionObserver(function (entries) {
            if (entries[0].isIntersecting) {
                if (!pixelAnimationId) animate();
            } else if (pixelAnimationId) {
                cancelAnimationFrame(pixelAnimationId);
                pixelAnimationId = null;
            }
        }, { threshold: 0.1 });
        pixelObserver.observe(grid);
    }

    var navMap = {
        "nav-about": "about",
        "nav-projects": "projects",
        "nav-contact": "contact"
    };

    Object.keys(navMap).forEach(function (radioId) {
        var radio = document.getElementById(radioId);
        if (!radio) return;
        radio.addEventListener("change", function () {
            var target = document.getElementById(navMap[radioId]);
            if (radio.checked && target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) entry.target.classList.add("visible");
        });
    }, { threshold: 0.08 });

    document.querySelectorAll(".fade-in").forEach(function (element) {
        observer.observe(element);
    });

    var mainContent = document.querySelector(".main-content");
    if (mainContent) mainContent.classList.add("loaded");
    var year = document.getElementById("year");
    if (year) year.textContent = new Date().getFullYear();

    var groupToggle = document.getElementById("groupToggle");
    var groupPanel = document.getElementById("groupPanel");
    var groupClose = document.getElementById("groupClose");
    function setGroupPanel(open) {
        if (!groupToggle || !groupPanel) return;
        groupPanel.classList.toggle("show", open);
        groupPanel.setAttribute("aria-hidden", String(!open));
        groupToggle.setAttribute("aria-expanded", String(open));
    }
    if (groupToggle) groupToggle.addEventListener("click", function () {
        setGroupPanel(!groupPanel.classList.contains("show"));
    });
    if (groupClose) groupClose.addEventListener("click", function () { setGroupPanel(false); });
    renderPixelBanner("随风而行");

    var resizeTimer;
    window.addEventListener("resize", function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () { renderPixelBanner("随风而行"); }, 180);
    });
})();
