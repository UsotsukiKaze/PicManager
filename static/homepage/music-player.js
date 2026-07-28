(function() {
    // 检查是否被禁用
    if (window.__musicPlayerDisabled) {
        var player = document.getElementById('musicPlayer');
        if (player) player.style.display = 'none';
        return;
    }

    var player = document.getElementById('musicPlayer');
    var audio = document.getElementById('musicAudio');
    var coverImg = document.getElementById('musicCover');
    var coverPlaceholder = document.getElementById('musicCoverPlaceholder');
    var titleEl = document.getElementById('musicTitle');
    var artistEl = document.getElementById('musicArtist');
    var playBtn = document.getElementById('musicPlay');
    var prevBtn = document.getElementById('musicPrev');
    var nextBtn = document.getElementById('musicNext');
    var iconPlay = playBtn.querySelector('.icon-play');
    var iconPause = playBtn.querySelector('.icon-pause');

    var progressWrap = document.getElementById('musicProgressWrap');
    var progressBar = document.getElementById('musicProgressBar');

    var isPlaying = false;
    var currentSong = null;
    var isLoading = false;
    var _progressRAF = null;

    // 读取配置
    var cfg = window.__musicPlayerConfig || {};
    var mode = cfg.mode || 'random';
    var playlist = cfg.playlist || [];
    var plIdx = -1; // 当前歌单索引

    // ---- 通用：设置当前歌曲 UI ----
    function applySong(song) {
        currentSong = song;
        progressBar.style.width = '0%';

        var coverUrl = song.cover || song.picurl || '';
        if (coverUrl) {
            coverImg.src = coverUrl;
            coverImg.onload = function() {
                coverImg.classList.add('loaded');
                coverPlaceholder.style.display = 'none';
            };
            coverImg.onerror = function() {
                coverImg.classList.remove('loaded');
                coverPlaceholder.style.display = 'flex';
            };
        } else {
            coverImg.classList.remove('loaded');
            coverPlaceholder.style.display = 'flex';
        }

        titleEl.textContent = song.name || '未知歌曲';
        artistEl.textContent = song.artist || song.artistsname || '未知歌手';

        if (song.url) {
            audio.src = song.url;
        } else {
            audio.removeAttribute('src');
        }
    }

    // ---- 随机模式：在线 API ----
    function loadRandomSong() {
        if (isLoading) return Promise.resolve(null);
        isLoading = true;
        titleEl.textContent = '加载中...';
        artistEl.textContent = '随机音乐';
        progressBar.style.width = '0%';

        return fetch('https://www.cunyuapi.top/rwyymusic')
            .then(function(r) { return r.json(); })
            .then(function(res) {
                var data = res || {};
                applySong({
                    name: data.name,
                    artist: data.artists,
                    cover: data.pic_url,
                    url: data.song_url
                });
                isLoading = false;
            })
            .catch(function(err) {
                console.error('加载音乐失败:', err);
                titleEl.textContent = '音乐接口不可用';
                artistEl.textContent = '请检查网络或稍后重试';
                isLoading = false;
                playBtn.disabled = true;
                prevBtn.disabled = true;
                nextBtn.disabled = true;
            });
    }

    // ---- 自定义模式：歌单切歌 ----
    function loadCustomSong(direction) {
        if (!playlist.length) return Promise.resolve(null);
        if (direction === 'next') {
            plIdx = (plIdx + 1) % playlist.length;
        } else if (direction === 'prev') {
            plIdx = (plIdx - 1 + playlist.length) % playlist.length;
        } else {
            plIdx = plIdx < 0 ? 0 : plIdx;
        }
        applySong(playlist[plIdx]);
        return Promise.resolve(null);
    }

    // ---- 统一加载接口 ----
    function loadSong(direction) {
        if (mode === 'custom') return loadCustomSong(direction);
        return loadRandomSong();
    }

    // 播放/暂停
    function togglePlay() {
        if (!audio.src && currentSong && currentSong.url) {
            audio.src = currentSong.url;
        }
        if (!audio.src) {
            loadSong('next').then(function() {
                if (audio.src) audio.play().catch(function(e) {
                    console.error('播放失败:', e);
                });
            });
            return;
        }
        if (isPlaying) {
            audio.pause();
        } else {
            audio.play().catch(function(e) {
                console.error('播放失败:', e);
            });
        }
    }

    // 更新播放状态 UI
    function updatePlayState(playing) {
        isPlaying = playing;
        if (playing) {
            iconPlay.style.display = 'none';
            iconPause.style.display = 'block';
            player.classList.add('playing');
            player.classList.add('show-progress');
        } else {
            iconPlay.style.display = 'block';
            iconPause.style.display = 'none';
            player.classList.remove('playing');
        }
    }

    // 事件绑定
    playBtn.addEventListener('click', togglePlay);

    prevBtn.addEventListener('click', function() {
        var wasPlaying = isPlaying;
        if (isPlaying) { audio.pause(); audio.currentTime = 0; }
        loadSong('prev').then(function() {
            if (wasPlaying && audio.src) audio.play().catch(function() {});
        });
    });

    nextBtn.addEventListener('click', function() {
        var wasPlaying = isPlaying;
        if (isPlaying) { audio.pause(); audio.currentTime = 0; }
        loadSong('next').then(function() {
            if (wasPlaying && audio.src) audio.play().catch(function() {});
        });
    });

    audio.addEventListener('play', function() {
        updatePlayState(true);
    });

    audio.addEventListener('pause', function() {
        updatePlayState(false);
    });

    audio.addEventListener('ended', function() {
        loadSong('next').then(function() {
            if (audio.src) audio.play().catch(function() {});
        });
    });

    // 进度条更新
    function updateProgress() {
        if (audio.duration && isFinite(audio.duration)) {
            var pct = (audio.currentTime / audio.duration) * 100;
            progressBar.style.width = pct + '%';
        }
        if (isPlaying) {
            _progressRAF = requestAnimationFrame(updateProgress);
        }
    }

    audio.addEventListener('play', function() {
        cancelAnimationFrame(_progressRAF);
        _progressRAF = requestAnimationFrame(updateProgress);
    });
    audio.addEventListener('pause', function() {
        cancelAnimationFrame(_progressRAF);
    });
    audio.addEventListener('seeked', function() {
        updateProgress();
    });

    // 点击进度条跳转
    if (progressWrap) {
        progressWrap.addEventListener('click', function(e) {
            if (!audio.duration || !isFinite(audio.duration)) return;
            var rect = progressWrap.getBoundingClientRect();
            var ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            audio.currentTime = ratio * audio.duration;
        });
    }

    // 点击胶囊切换进度条显隐
    player.addEventListener('click', function(e) {
        if (e.target.closest('.music-btn') || e.target.closest('.music-progress-wrap')) return;
        player.classList.toggle('show-progress');
    });

    if (mode === 'custom') {
        loadSong('next').then(function() {
            audio.play().catch(function() {
                // 浏览器禁止自动播放时，保留播放按钮供用户手动启动。
            });
        });
    }
})();
