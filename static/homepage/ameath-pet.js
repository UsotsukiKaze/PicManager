(function () {
    "use strict";

    var pet = document.getElementById("ameathPet");
    var image = document.getElementById("ameathPetImage");
    var voiceAudio = document.getElementById("ameathVoiceAudio");
    var lyricBubble = document.getElementById("ameathLyric");
    if (!pet || !image || !voiceAudio || !lyricBubble) return;

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
    var lyricLines = [];
    var lyricSong = null;
    var lyricLoadToken = 0;
    var activeLyricKey = null;
    var lyricResizeToken = 0;
    var lyricsRequested = false;
    var lyricCache = new Map();
    var resolvedLyricCache = new Map();
    var noteLyricLayout = null;
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
        lyricBubble.classList.toggle("align-left", state.x < 25);
        lyricBubble.classList.toggle("align-right", state.x > 68);
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

    function parseLyrics(text, startAt, pairMode, lyricOffset) {
        var rawLines = text.split(/\r?\n/).reduce(function(lines, line) {
            var match = line.match(/^\[(\d{2}):(\d{2}(?:\.\d+)?)\]\s*(.+?)\s*$/);
            if (!match) return lines;
            var sourceTime = Number(match[1]) * 60 + Number(match[2]);
            var value = match[3].trim();
            if (!value || sourceTime < startAt) return lines;
            var time = Math.max(0, sourceTime + (Number(lyricOffset) || 0));
            lines.push({ time: time, text: value });
            return lines;
        }, []);

        var grouped = [];
        for (var index = 0; index < rawLines.length; index += 1) {
            var current = rawLines[index];
            var next = rawLines[index + 1];
            var currentIsCjk = /[\u3400-\u9fff]/.test(current.text);
            var nextIsCjk = next && /[\u3400-\u9fff]/.test(next.text);
            var shouldPair = !currentIsCjk && nextIsCjk && (
                pairMode === "alternating" || next.time - current.time <= 12
            );
            if (shouldPair) {
                grouped.push({ time: current.time, original: current.text, translation: next.text });
                index += 1;
            } else {
                grouped.push({ time: current.time, original: current.text, translation: "" });
            }
        }
        return grouped;
    }

    function createLyricCopy(line) {
        var copy = document.createElement("span");
        copy.className = "ameath-lyric-copy";
        if (line && line.fontSize) copy.style.fontSize = line.fontSize + "px";
        var original = document.createElement("span");
        original.className = "ameath-lyric-original";
        original.textContent = line ? line.original : "♪～";
        copy.appendChild(original);
        if (line && line.translation) {
            var translation = document.createElement("span");
            translation.className = "ameath-lyric-translation";
            translation.textContent = line.translation;
            copy.appendChild(translation);
        }
        return copy;
    }

    function measureLyricLayouts(lines) {
        if (lines._layoutsReady && noteLyricLayout) return;
        var measure = document.createElement("span");
        measure.className = "ameath-lyric lyric-measure";
        document.body.appendChild(measure);
        var candidates = [null].concat(lines);
        candidates.forEach(function(line) {
            if (line) delete line.fontSize;
            measure.replaceChildren(createLyricCopy(line));
            var rect = measure.getBoundingClientRect();
            var availableWidth = Math.max(220, window.innerWidth - 28);
            if (line && rect.width > availableWidth) {
                line.fontSize = Math.max(7.5, 11 * availableWidth / rect.width);
                measure.replaceChildren(createLyricCopy(line));
                rect = measure.getBoundingClientRect();
            }
            var layout = { width: Math.ceil(rect.width), height: Math.ceil(rect.height) };
            if (line) line.layout = layout;
            else noteLyricLayout = layout;
        });
        measure.remove();
        lines._layoutsReady = true;
    }

    function removeLyricCopy(copy) {
        if (!copy) return;
        if (copy.getAnimations) {
            copy.getAnimations().forEach(function(animation) { animation.cancel(); });
        }
        copy.remove();
    }

    function clearLyricCopies() {
        lyricBubble.querySelectorAll(".ameath-lyric-copy").forEach(removeLyricCopy);
    }

    function renderLyric(line) {
        var key = line ? String(line.time) : "note";
        if (key === activeLyricKey) return;
        activeLyricKey = key;
        var layout = (line && line.layout) || noteLyricLayout || { width: 72, height: 35 };
        var previousCopies = Array.from(lyricBubble.querySelectorAll(".ameath-lyric-copy"));
        var copy = createLyricCopy(line);
        copy.style.width = Math.max(28, layout.width - 26) + "px";
        lyricBubble.appendChild(copy);
        lyricBubble.style.width = layout.width + "px";
        lyricBubble.style.height = layout.height + "px";
        lyricResizeToken += 1;
        previousCopies.forEach(function(previousCopy) {
            if (previousCopy.getAnimations) {
                previousCopy.getAnimations().forEach(function(animation) { animation.cancel(); });
            }
            if (previousCopy.animate) {
                previousCopy.animate([
                    { opacity: 1, transform: "translateY(0)", filter: "blur(0)" },
                    { opacity: 0, transform: "translateY(-2px)", filter: "blur(1px)" }
                ], { duration: 280, easing: "ease-out", fill: "forwards" });
            }
            window.setTimeout(function() {
                if (previousCopy.isConnected) removeLyricCopy(previousCopy);
            }, 300);
        });
        if (copy.animate) {
            copy.animate([
                { opacity: 0, transform: "translateY(3px)", filter: "blur(1px)" },
                { opacity: 1, transform: "translateY(0)", filter: "blur(0)" }
            ], { duration: 520, delay: previousCopies.length ? 80 : 0, easing: "cubic-bezier(.16, 1, .3, 1)", fill: "both" });
        }
    }

    function lyricCacheKey(song) {
        return [song.lyric, song.lyricStart, song.lyricPairMode, song.lyricOffset].join("|");
    }

    function fetchLyrics(song) {
        if (!song || !song.lyric) return Promise.resolve([]);
        var cacheKey = lyricCacheKey(song);
        if (lyricCache.has(cacheKey)) return lyricCache.get(cacheKey);
        var request = fetch(song.lyric, { cache: "no-store" })
            .then(function(response) {
                if (!response.ok) throw new Error("lyric request failed");
                return response.text();
            })
            .then(function(text) {
                return parseLyrics(
                    text,
                    Number(song.lyricStart) || 0,
                    song.lyricPairMode || "",
                    Number(song.lyricOffset) || 0
                );
            })
            .catch(function() { return []; })
            .then(function(lines) {
                measureLyricLayouts(lines);
                resolvedLyricCache.set(cacheKey, lines);
                return lines;
            });
        lyricCache.set(cacheKey, request);
        return request;
    }

    function loadLyrics(song) {
        clearLyricCopies();
        lyricSong = song || null;
        lyricLines = [];
        activeLyricKey = null;
        var token = ++lyricLoadToken;
        if (!song || !song.lyric) {
            measureLyricLayouts([]);
            renderLyric(null);
            return;
        }
        var cacheKey = lyricCacheKey(song);
        if (resolvedLyricCache.has(cacheKey)) {
            lyricLines = resolvedLyricCache.get(cacheKey);
            measureLyricLayouts(lyricLines);
            renderLyric(null);
            return;
        }
        measureLyricLayouts([]);
        renderLyric(null);
        fetchLyrics(song)
            .then(function(lines) {
                if (token !== lyricLoadToken) return;
                lyricLines = lines;
                measureLyricLayouts(lyricLines);
            });
    }

    function preloadConfiguredLyrics() {
        var config = window.__musicPlayerConfig || {};
        var songs = (config.playlist || []).concat(config.ameathPlaylist || []);
        songs.forEach(function(song) { fetchLyrics(song); });
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
        var detail = event.detail || {};
        isSinging = Boolean(detail.singing);
        clearTimeout(idleTimer);
        if (isSinging) {
            state.moving = false;
            pet.classList.remove("is-moving", "is-curious");
            setImage("/static/homepage/ameath/ameath.gif");
            loadLyrics(detail.song);
            lyricBubble.classList.add("show");
        } else {
            if (!lyricsRequested) {
                lyricLoadToken += 1;
                lyricSong = null;
                lyricLines = [];
                activeLyricKey = null;
                lyricBubble.classList.remove("show");
            }
            rest();
        }
    });

    window.addEventListener("homepage:lyrics-mode", function(event) {
        var detail = event.detail || {};
        lyricsRequested = Boolean(detail.enabled);
        if (lyricsRequested) {
            loadLyrics(detail.song);
            lyricBubble.classList.add("show");
        } else if (!isSinging) {
            lyricLoadToken += 1;
            lyricSong = null;
            lyricLines = [];
            activeLyricKey = null;
            lyricBubble.classList.remove("show");
        }
    });

    window.addEventListener("homepage:lyric-time", function(event) {
        if ((!isSinging && !lyricsRequested) || !lyricSong) return;
        var detail = event.detail || {};
        if (detail.song !== lyricSong) return;
        var currentTime = Number(detail.currentTime) || 0;
        var activeLine = null;
        for (var index = 0; index < lyricLines.length; index += 1) {
            if (lyricLines[index].time > currentTime) break;
            activeLine = lyricLines[index];
        }
        renderLyric(activeLine);
    });

    preloadConfiguredLyrics();
    setPosition();
    rest();
    tick();
    window.addEventListener("beforeunload", function () { cancelAnimationFrame(frameHandle); });
})();
