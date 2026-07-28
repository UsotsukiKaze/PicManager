(function () {
  "use strict";

  const $all = (selector) => Array.from(document.querySelectorAll(selector));

  function safeUrl(value, fallback) {
    try {
      const url = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function setText(selector, value) {
    $all(selector).forEach((node) => {
      node.textContent = value;
    });
  }

  function renderSkills(skills) {
    const container = document.querySelector("[data-skills]");
    if (!container) return;
    container.replaceChildren(
      ...skills.map((skill) => {
        const tag = document.createElement("span");
        tag.className = "skill-tag";
        tag.textContent = skill;
        return tag;
      })
    );
  }

  function renderProjects(projects) {
    const container = document.querySelector("[data-projects]");
    if (!container) return;

    const cards = projects.map((project, index) => {
      const card = document.createElement("a");
      card.className = "project-item project-link";
      card.dataset.index = String(index + 1).padStart(2, "0");
      card.href = safeUrl(project.url, "#");
      card.target = "_blank";
      card.rel = "noopener noreferrer";

      const icon = document.createElement("div");
      icon.className = "project-icon";
      icon.textContent = project.title.slice(0, 1).toUpperCase();

      const title = document.createElement("div");
      title.className = "project-title";
      title.textContent = project.title;

      const description = document.createElement("div");
      description.className = "project-desc";
      description.textContent = project.description;

      const action = document.createElement("div");
      action.className = "project-action";
      action.textContent = `${project.label} ↗`;

      card.append(icon, title, description, action);
      return card;
    });

    container.replaceChildren(...cards);
  }

  function renderAvatar(url, displayName) {
    const avatar = document.getElementById("avatar");
    if (!avatar) return;
    if (!url) {
      const initials = avatar.querySelector(".avatar-initials");
      if (initials) {
        initials.textContent = displayName
          .split(/[\s_-]+/)
          .map((part) => part[0])
          .join("")
          .slice(0, 2)
          .toUpperCase();
      }
      return;
    }

    const image = document.createElement("img");
    image.className = "avatar-img";
    image.alt = `${displayName} 的头像`;
    image.src = safeUrl(url, "");
    image.addEventListener("error", () => image.remove(), { once: true });
    avatar.replaceChildren(image);
  }

  function applyConfig(config) {
    document.title = `${config.display_name} · Personal Space`;
    setText("[data-site-name]", config.display_name);
    setText("[data-welcome]", config.welcome);
    setText("[data-subtitle]", config.subtitle);
    setText("[data-pixel-text]", config.pixel_text);
    setText("[data-introduction]", config.introduction);

    const github = document.querySelector("[data-github]");
    if (github) {
      github.href = safeUrl(config.github_url, "https://github.com/UsotsukiKaze");
      github.firstChild.textContent = `${new URL(github.href).host}${new URL(github.href).pathname} `;
    }

    document.documentElement.style.setProperty("--site-accent", config.appearance.accent);
    document.documentElement.style.setProperty("--site-accent-secondary", config.appearance.accent_secondary);
    renderAvatar(config.avatar_url, config.display_name);
    renderSkills(config.skills);
    renderProjects(config.projects);
  }

  function showError() {
    const notice = document.createElement("div");
    notice.className = "load-error";
    notice.textContent = "站点配置暂时无法读取，正在显示默认内容。";
    document.body.appendChild(notice);
  }

  document.querySelector("[data-year]").textContent = new Date().getFullYear();

  fetch("/api/site/config", { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("Config request failed");
      return response.json();
    })
    .then(applyConfig)
    .catch(showError);

  const navLinks = $all(".simple-nav a");
  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      navLinks.forEach((item) => item.classList.remove("active"));
      link.classList.add("active");
    });
  });
})();
