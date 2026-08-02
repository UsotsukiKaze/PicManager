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
    var lyricsBtn = document.getElementById('musicLyrics');
    var iconPlay = playBtn.querySelector('.icon-play');
    var iconPause = playBtn.querySelector('.icon-pause');

    var progressWrap = document.getElementById('musicProgressWrap');
    var progressBar = document.getElementById('musicProgressBar');
    var playlistEl = document.getElementById('musicPlaylistItems');
    var playlistModeEl = document.getElementById('musicPlaylistMode');
    var volumeInput = document.getElementById('musicVolume');

    var isPlaying = false;
    var currentSong = null;
    var isLoading = false;
    var _progressRAF = null;
    var defaultLyricsEnabled = false;

    // 读取配置
    var cfg = window.__musicPlayerConfig || {};
    var mode = cfg.mode || 'random';
    var playlists = {
        "default": cfg.playlist || [],
        ameath: cfg.ameathPlaylist || []
    };
    var activePlaylist = "default";
    var playlist = playlists[activePlaylist];
    var plIdx = -1; // 当前歌单索引

    function updateLyricsButton() {
        if (!lyricsBtn) return;
        var forced = activePlaylist === 'ameath';
        var enabled = forced || defaultLyricsEnabled;
        lyricsBtn.classList.toggle('active', enabled);
        lyricsBtn.setAttribute('aria-pressed', String(enabled));
        lyricsBtn.setAttribute('aria-disabled', String(forced));
        lyricsBtn.title = forced ? '小爱歌单会自动显示歌词' : (enabled ? '关闭歌词' : '显示歌词');
    }

    function dispatchDefaultLyrics() {
        window.dispatchEvent(new CustomEvent('homepage:lyrics-mode', {
            detail: {
                enabled: activePlaylist === 'default' && defaultLyricsEnabled,
                song: currentSong
            }
        }));
    }

    function updateTextScroll(element) {
        window.requestAnimationFrame(function() {
            var overflow = Math.ceil(element.scrollWidth - element.clientWidth);
            element.classList.toggle('is-scrolling', overflow > 4);
            element.style.setProperty('--music-scroll-distance', '-' + Math.max(0, overflow + 10) + 'px');
        });
    }

    function renderPlaylist() {
        if (!playlistEl) return;
        primePlaylistDurations(playlist);
        playlistEl.replaceChildren();
        if (playlistModeEl) playlistModeEl.textContent = activePlaylist === 'ameath' ? '小爱歌单' : '默认歌单';
        playlist.forEach(function(song, index) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'music-playlist-item' + (song === currentSong ? ' active' : '');
            item.title = song.artist || '';
            var cover = document.createElement('img');
            cover.className = 'music-playlist-cover cover-variant-' + (index % 4);
            cover.src = song.playlistCover || song.cover || song.picurl || '/static/homepage/background.jpg';
            cover.alt = '';
            var detail = document.createElement('span');
            detail.className = 'music-playlist-detail';
            var name = document.createElement('span');
            name.className = 'music-playlist-name';
            name.textContent = song.name || '未知歌曲';
            var artist = document.createElement('span');
            artist.className = 'music-playlist-artist';
            artist.textContent = song.artist || song.artistsname || '未知歌手';
            var duration = document.createElement('time');
            duration.className = 'music-playlist-duration';
            duration.textContent = song.durationText || '—:—';
            detail.append(name, artist);
            item.append(cover, detail, duration);
            item.addEventListener('click', function(event) {
                event.stopPropagation();
                var wasPlaying = isPlaying;
                if (isPlaying) audio.pause();
                plIdx = index;
                applySong(playlist[plIdx]);
                if (wasPlaying) audio.play().catch(function() {});
            });
            playlistEl.appendChild(item);
        });
    }

    function setVolume(value) {
        var normalized = Math.max(0, Math.min(100, Number(value))) / 100;
        audio.volume = normalized;
        if (volumeInput) volumeInput.value = String(Math.round(normalized * 100));
        try { window.localStorage.setItem('homepage-music-volume', String(normalized)); } catch (error) {}
    }

    function formatDuration(seconds) {
        if (!Number.isFinite(seconds) || seconds <= 0) return '—:—';
        var total = Math.round(seconds);
        return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
    }

    // 仅预读元数据，不播放也不下载完整音频；让列表能显示真实时长。
    function primePlaylistDurations(songs) {
        songs.forEach(function(song) {
            if (!song.url || song.durationText || song.durationLoading) return;
            song.durationLoading = true;
            var probe = document.createElement('audio');
            probe.preload = 'metadata';
            probe.addEventListener('loadedmetadata', function() {
                song.durationText = formatDuration(probe.duration);
                song.durationLoading = false;
                probe.removeAttribute('src');
                probe.load();
                renderPlaylist();
            }, { once: true });
            probe.addEventListener('error', function() {
                song.durationLoading = false;
            }, { once: true });
            probe.src = song.url;
        });
    }

    try {
        var savedVolume = window.localStorage.getItem('homepage-music-volume');
        setVolume(savedVolume === null ? 70 : Number(savedVolume) * 100);
    } catch (error) {
        setVolume(70);
    }
    if (volumeInput) volumeInput.addEventListener('input', function() { setVolume(volumeInput.value); });

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
        updateTextScroll(titleEl);
        updateTextScroll(artistEl);
        renderPlaylist();

        if (activePlaylist === 'ameath') {
            window.dispatchEvent(new CustomEvent('homepage:pet-state', {
                detail: { singing: true, song: song }
            }));
        } else if (defaultLyricsEnabled) {
            dispatchDefaultLyrics();
        }

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

    if (lyricsBtn) {
        lyricsBtn.addEventListener('click', function() {
            if (activePlaylist !== 'default') return;
            defaultLyricsEnabled = !defaultLyricsEnabled;
            updateLyricsButton();
            dispatchDefaultLyrics();
        });
    }

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

    window.addEventListener('homepage:play-track', function(event) {
        var requestedId = event.detail && event.detail.id;
        if (!requestedId || mode !== 'custom') return;
        var requestedIndex = playlist.findIndex(function(song) { return song.id === requestedId; });
        if (requestedIndex < 0) return;

        plIdx = requestedIndex;
        applySong(playlist[plIdx]);
        audio.play().catch(function() {
            // 某些浏览器会限制非点击触发的播放；点击爱弥斯时可正常播放。
        });
    });

    window.addEventListener('homepage:select-playlist', function(event) {
        var detail = event.detail || {};
        var requestedPlaylist = detail.name;
        if (mode !== 'custom' || !playlists[requestedPlaylist] || !playlists[requestedPlaylist].length) return;

        activePlaylist = requestedPlaylist;
        playlist = playlists[activePlaylist];
        updateLyricsButton();
        plIdx = 0;
        if (isPlaying) audio.pause();
        applySong(playlist[plIdx]);
        if (activePlaylist !== 'ameath') {
            window.dispatchEvent(new CustomEvent('homepage:pet-state', {
                detail: { singing: false }
            }));
            dispatchDefaultLyrics();
        }

        if (detail.play) {
            audio.play().catch(function() {
                // 浏览器会允许由双击触发的这次播放；其他情况保留播放按钮。
            });
        }
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

    audio.addEventListener('loadedmetadata', function() {
        if (!currentSong) return;
        currentSong.durationText = formatDuration(audio.duration);
        renderPlaylist();
    });

    audio.addEventListener('timeupdate', function() {
        if ((activePlaylist !== 'ameath' && !defaultLyricsEnabled) || !currentSong) return;
        window.dispatchEvent(new CustomEvent('homepage:lyric-time', {
            detail: { song: currentSong, currentTime: audio.currentTime }
        }));
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
        if (e.target.closest('.music-btn') || e.target.closest('.music-progress-wrap') || e.target.closest('.music-playlist') || e.target.closest('.music-volume')) return;
        player.classList.toggle('show-progress');
    });

    if (mode === 'custom') {
        updateLyricsButton();
        loadSong('next').then(function() {
            audio.play().catch(function() {
                // 浏览器禁止自动播放时，保留播放按钮供用户手动启动。
            });
        });
    }
})();
