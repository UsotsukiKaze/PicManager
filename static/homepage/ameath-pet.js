(function () {
    "use strict";

    var pet = document.getElementById("ameathPet");
    var image = document.getElementById("ameathPetImage");
    var voiceAudio = document.getElementById("ameathVoiceAudio");
    if (!pet || !image || !voiceAudio) return;

    var assets = {
        move: "/static/homepage/ameath/move.gif",
        idle: [
            "/static/homepage/ameath/idle1.gif",
            "/static/homepage/ameath/idle2.gif",
            "/static/homepage/ameath/idle3.gif",
            "/static/homepage/ameath/idle4.gif"
        ],
        curious: "/static/homepage/ameath/drag.gif"
    };
    var voicePlaylist = (window.__musicPlayerConfig && window.__musicPlayerConfig.voicePlaylist) || [];
    var state = { x: 18, y: 72, targetX: 18, targetY: 72, moving: false, hovering: false };
    var frameHandle = null;
    var idleTimer = null;
    var clickCount = 0;
    var clickTimer = null;
    var isSinging = false;
    var dragging = false;
    var didDrag = false;
    var dragPointerId = null;
    var dragStartX = 0;
    var dragStartY = 0;

    function setImage(source) {
        if (!image.src.endsWith(source)) image.src = source;
    }

    function viewportPoint() {
        var lanes = [13, 74, 84];
        var lane = lanes[Math.floor(Math.random() * lanes.length)];
        var fromLeft = Math.random() < 0.5;

        return {
            x: fromLeft ? 2 + Math.random() * 11 : 84 + Math.random() * 10,
            y: lane + (Math.random() * 8 - 4)
        };
    }

    function setPosition() {
        pet.style.left = state.x + "vw";
        pet.style.top = state.y + "vh";
    }

    function chooseTarget() {
        if (isSinging) return;
        var point = viewportPoint();
        state.targetX = point.x;
        state.targetY = point.y;
        state.moving = true;
        pet.classList.add("is-moving");
        setImage(assets.move);
    }

    function rest() {
        if (isSinging) return;
        state.moving = false;
        pet.classList.remove("is-moving");
        setImage(assets.idle[Math.floor(Math.random() * assets.idle.length)]);
        clearTimeout(idleTimer);
        idleTimer = setTimeout(chooseTarget, 2200 + Math.random() * 4500);
    }

    function tick() {
        if (state.moving && !state.hovering) {
            var dx = state.targetX - state.x;
            var dy = state.targetY - state.y;
            var distance = Math.sqrt(dx * dx + dy * dy);
            if (distance < 0.18) {
                rest();
            } else {
                var speed = 0.022;
                state.x += dx / distance * speed;
                state.y += dy / distance * speed;
                image.classList.toggle("is-facing-left", dx < 0);
                setPosition();
            }
        }
        frameHandle = requestAnimationFrame(tick);
    }

    function playVoice() {
        if (!voicePlaylist.length) return;
        var voice = voicePlaylist[Math.floor(Math.random() * voicePlaylist.length)];
        voiceAudio.src = voice.url;
        voiceAudio.currentTime = 0;
        voiceAudio.play().catch(function () {
            // 单击通常可播放；若被浏览器拦截，不影响当前音乐。
        });
    }

    pet.addEventListener("pointerenter", function () {
        if (dragging) return;
        if (isSinging) {
            pet.classList.add("is-curious");
            return;
        }
        state.hovering = true;
        state.moving = false;
        clearTimeout(idleTimer);
        pet.classList.add("is-curious");
        setImage(assets.curious);
    });

    pet.addEventListener("pointerleave", function () {
        if (dragging) return;
        if (isSinging) {
            pet.classList.remove("is-curious");
            return;
        }
        state.hovering = false;
        pet.classList.remove("is-curious");
        if (!isSinging) rest();
    });

    pet.addEventListener("click", function () {
        if (didDrag) return;
        clickCount += 1;
        clearTimeout(clickTimer);
        clickTimer = window.setTimeout(function () {
            if (clickCount === 1) {
                playVoice();
            } else if (clickCount === 2) {
                window.dispatchEvent(new CustomEvent("homepage:select-playlist", {
                    detail: { name: "ameath", play: true }
                }));
            } else {
                window.dispatchEvent(new CustomEvent("homepage:select-playlist", {
                    detail: { name: "default", play: true }
                }));
            }
            clickCount = 0;
        }, 320);
        pet.classList.add("is-reacting");
        window.setTimeout(function () { pet.classList.remove("is-reacting"); }, 520);
    });

    pet.addEventListener("pointerdown", function (event) {
        dragPointerId = event.pointerId;
        dragStartX = event.clientX;
        dragStartY = event.clientY;
        didDrag = false;
        state.moving = false;
        clearTimeout(idleTimer);
        pet.setPointerCapture(event.pointerId);
    });

    pet.addEventListener("pointermove", function (event) {
        if (event.pointerId !== dragPointerId) return;
        if (!dragging && Math.hypot(event.clientX - dragStartX, event.clientY - dragStartY) < 4) return;

        dragging = true;
        didDrag = true;
        pet.classList.add("is-dragging");
        setImage(assets.curious);
        state.x = Math.max(4, Math.min(96, event.clientX / window.innerWidth * 100));
        state.y = Math.max(6, Math.min(94, event.clientY / window.innerHeight * 100));
        setPosition();
    });

    pet.addEventListener("pointerup", function (event) {
        if (event.pointerId !== dragPointerId) return;
        if (pet.hasPointerCapture(event.pointerId)) pet.releasePointerCapture(event.pointerId);
        dragPointerId = null;
        dragging = false;
        pet.classList.remove("is-dragging");
        if (isSinging) {
            setImage("/static/homepage/ameath/ameath.gif");
        } else {
            rest();
        }
        window.setTimeout(function () { didDrag = false; }, 0);
    });

    window.addEventListener("homepage:pet-state", function (event) {
        isSinging = Boolean(event.detail && event.detail.singing);
        clearTimeout(idleTimer);
        if (isSinging) {
            state.moving = false;
            pet.classList.remove("is-moving", "is-curious");
            setImage("/static/homepage/ameath/ameath.gif");
        } else {
            rest();
        }
    });

    setPosition();
    rest();
    tick();
    window.addEventListener("beforeunload", function () { cancelAnimationFrame(frameHandle); });
})();
