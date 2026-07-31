(function () {
    "use strict";

    var form = document.getElementById("guestbookForm");
    var nicknameInput = document.getElementById("guestbookNickname");
    var contentInput = document.getElementById("guestbookContent");
    var hint = document.getElementById("guestbookHint");
    var list = document.getElementById("guestbookList");
    var count = document.getElementById("guestbookCount");
    var avatarUrl = "/static/homepage/ameath/ameath_content.png";
    var canManage = false;
    var latestMessages = [];

    if (!form || !nicknameInput || !contentInput || !hint || !list || !count) return;

    function formatTime(value) {
        var date = new Date(value);
        return Number.isNaN(date.getTime()) ? "刚刚" : date.toLocaleString("zh-CN", {
            timeZone: "Asia/Shanghai",
            month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
        });
    }

    function renderMessages(messages) {
        latestMessages = messages;
        list.replaceChildren();
        count.textContent = messages.length ? messages.length + " 条" : "";
        if (!messages.length) {
            var empty = document.createElement("p");
            empty.className = "guestbook-empty";
            empty.textContent = "还没有留言，来做第一个留下痕迹的人吧。";
            list.appendChild(empty);
            return;
        }

        messages.forEach(function (message) {
            var item = document.createElement("article");
            item.className = "guestbook-message";
            item.appendChild(buildMessage(message, false));
            (message.replies || []).forEach(function (reply) {
                var replyItem = document.createElement("article");
                replyItem.className = "guestbook-message guestbook-reply";
                replyItem.appendChild(buildMessage(reply, true));
                item.appendChild(replyItem);
            });
            list.appendChild(item);
        });
    }

    function buildMessage(message, isReply) {
        var fragment = document.createDocumentFragment();
        var row = document.createElement("div");
        row.className = "guestbook-message-row";
            var avatar = document.createElement("img");
            avatar.className = "guestbook-avatar";
            avatar.src = message.is_owner ? "/static/homepage/avatar.jpg" : avatarUrl;
            avatar.alt = "";
            var body = document.createElement("div");
            body.className = "guestbook-message-body";
            var meta = document.createElement("div");
            meta.className = "guestbook-message-meta";
            var name = document.createElement("strong");
            name.textContent = message.nickname;
            var time = document.createElement("time");
            time.dateTime = message.created_at;
            time.textContent = formatTime(message.created_at);
            var content = document.createElement("p");
            content.textContent = message.content;
            meta.append(name, time);
            body.append(meta, content);
        row.append(avatar, body);
        fragment.appendChild(row);

        if (canManage) {
            var controls = document.createElement("div");
            controls.className = "guestbook-admin-actions";
            if (!isReply) {
                var replyButton = document.createElement("button");
                replyButton.type = "button";
                replyButton.textContent = "回复";
                replyButton.addEventListener("click", function () { showReplyForm(message.id, controls); });
                controls.appendChild(replyButton);
            }
            var deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.textContent = "删除";
            deleteButton.addEventListener("click", function () { deleteMessage(message.id); });
            controls.appendChild(deleteButton);
            fragment.appendChild(controls);
        }
        return fragment;
    }

    function showReplyForm(messageId, controls) {
        if (controls.parentElement.querySelector(".guestbook-reply-form")) return;
        var replyForm = document.createElement("form");
        replyForm.className = "guestbook-reply-form";
        var textarea = document.createElement("textarea");
        textarea.maxLength = 500;
        textarea.rows = 2;
        textarea.placeholder = "以 UsotsukiKaze 的身份回复…";
        textarea.required = true;
        var submit = document.createElement("button");
        submit.type = "submit";
        submit.textContent = "发送回复";
        replyForm.append(textarea, submit);
        replyForm.addEventListener("submit", function (event) {
            event.preventDefault();
            var content = textarea.value.trim();
            if (!content) return;
            submit.disabled = true;
            fetch("/api/guestbook/" + messageId + "/replies", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: content })
            }).then(handleResponse).then(function () {
                loadMessages();
            }).catch(function () {
                submit.disabled = false;
            });
        });
        controls.parentElement.appendChild(replyForm);
        textarea.focus();
    }

    function deleteMessage(messageId) {
        if (!window.confirm("确定删除这条留言吗？")) return;
        fetch("/api/guestbook/" + messageId, { method: "DELETE" })
            .then(function (response) {
                if (!response.ok) throw new Error("删除失败");
                return loadMessages();
            })
            .catch(function () {});
    }

    function handleResponse(response) {
        return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.detail || "操作失败");
            return data;
        });
    }

    function loadMessages() {
        return fetch("/api/guestbook")
            .then(handleResponse)
            .then(function (data) { renderMessages(data.messages || []); })
            .catch(function () {
                list.innerHTML = "";
                var error = document.createElement("p");
                error.className = "guestbook-empty";
                error.textContent = "暂时无法加载留言。";
                list.appendChild(error);
            });
    }

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        var nickname = nicknameInput.value.trim();
        var content = contentInput.value.trim();
        if (!nickname || !content) return;

        hint.textContent = "发送中…";
        form.querySelector("button").disabled = true;
        fetch("/api/guestbook", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nickname: nickname, content: content })
        }).then(handleResponse).then(function () {
            contentInput.value = "";
            hint.textContent = "留言已送达。";
            loadMessages();
        }).catch(function (error) {
            hint.textContent = error.message || "发送失败，请稍后重试。";
        }).finally(function () {
            form.querySelector("button").disabled = false;
        });
    });

    fetch("/api/guestbook/permissions")
        .then(handleResponse)
        .then(function (data) {
            canManage = Boolean(data.can_manage);
            renderMessages(latestMessages);
        })
        .catch(function () {});
    loadMessages();
})();
