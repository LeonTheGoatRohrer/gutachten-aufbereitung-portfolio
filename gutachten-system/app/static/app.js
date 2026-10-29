(function () {
  const appLoader = document.querySelector("[data-app-loader]");
  if (appLoader) {
    const startedAt = window.performance ? window.performance.now() : Date.now();
    const minVisibleMs = 720;

    function hideAppLoader() {
      const now = window.performance ? window.performance.now() : Date.now();
      const delay = Math.max(minVisibleMs - (now - startedAt), 0);
      window.setTimeout(() => {
        appLoader.classList.add("is-hidden");
        window.setTimeout(() => {
          appLoader.setAttribute("hidden", "");
        }, 460);
      }, delay);
    }

    if (document.readyState === "complete") {
      hideAppLoader();
    } else {
      window.addEventListener("load", hideAppLoader, { once: true });
    }
  }

  const modal = document.querySelector("[data-welcome-modal]");
  if (modal) {
    const storageKey = "gutachtenSystemWelcomeSeen";
    const openButtons = document.querySelectorAll("[data-open-welcome]");
    const closeButtons = document.querySelectorAll("[data-close-welcome]");

    function openModal() {
      modal.hidden = false;
      document.body.classList.add("modal-open");
    }

    function closeModal() {
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      window.localStorage.setItem(storageKey, "1");
    }

    if (!window.localStorage.getItem(storageKey)) {
      openModal();
    }

    openButtons.forEach((button) => {
      button.addEventListener("click", openModal);
    });

    closeButtons.forEach((button) => {
      button.addEventListener("click", closeModal);
    });

    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeModal();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) {
        closeModal();
      }
    });
  }

  const zipCrcTable = (() => {
    const table = new Uint32Array(256);
    for (let index = 0; index < table.length; index += 1) {
      let value = index;
      for (let bit = 0; bit < 8; bit += 1) {
        value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      }
      table[index] = value >>> 0;
    }
    return table;
  })();

  const zipUint32Max = 0xffffffff;

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) {
      return "";
    }
    if (bytes < 1024 * 1024) {
      return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function normalizeZipPath(value) {
    return String(value || "")
      .replace(/\\/g, "/")
      .split("/")
      .filter((part) => part && part !== "." && part !== "..")
      .join("/");
  }

  function rootNameForFiles(files) {
    const firstPath = normalizeZipPath(files[0]?.webkitRelativePath || files[0]?.name || "Projektordner");
    const parts = firstPath.split("/").filter(Boolean);
    if (parts.length > 1) {
      return parts[0];
    }
    if (files.length === 1 && parts[0]) {
      return parts[0].replace(/\.zip$/i, "") || "Projektordner";
    }
    return "Projektordner";
  }

  function entryNameForFile(file, rootName) {
    const path = normalizeZipPath(file.webkitRelativePath || file.name);
    const parts = path.split("/").filter(Boolean);
    if (parts.length > 1 && parts[0] === rootName) {
      return parts.slice(1).join("/");
    }
    return path || file.name || "datei";
  }

  function dosDateTime(date) {
    const safeDate = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
    const year = Math.max(safeDate.getFullYear(), 1980);
    return {
      date: ((year - 1980) << 9) | ((safeDate.getMonth() + 1) << 5) | safeDate.getDate(),
      time: (safeDate.getHours() << 11) | (safeDate.getMinutes() << 5) | Math.floor(safeDate.getSeconds() / 2),
    };
  }

  function updateCrc32(crc, bytes) {
    let value = crc;
    for (let index = 0; index < bytes.length; index += 1) {
      value = zipCrcTable[(value ^ bytes[index]) & 0xff] ^ (value >>> 8);
    }
    return value >>> 0;
  }

  async function crc32ForFile(file, onChunk) {
    let crc = 0xffffffff;
    if (file.stream) {
      const reader = file.stream().getReader();
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        crc = updateCrc32(crc, chunk.value);
        if (onChunk) {
          onChunk(chunk.value.byteLength || chunk.value.length || 0);
        }
      }
    } else {
      const bytes = new Uint8Array(await file.arrayBuffer());
      crc = updateCrc32(crc, bytes);
      if (onChunk) {
        onChunk(bytes.byteLength || bytes.length || 0);
      }
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function localZipHeader({ crc, size, nameBytes, modified }) {
    const header = new Uint8Array(30);
    const view = new DataView(header.buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 0x0800, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, modified.time, true);
    view.setUint16(12, modified.date, true);
    view.setUint32(14, crc, true);
    view.setUint32(18, size, true);
    view.setUint32(22, size, true);
    view.setUint16(26, nameBytes.length, true);
    view.setUint16(28, 0, true);
    return header;
  }

  function centralZipHeader({ crc, size, nameBytes, modified, offset }) {
    const header = new Uint8Array(46);
    const view = new DataView(header.buffer);
    view.setUint32(0, 0x02014b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 20, true);
    view.setUint16(8, 0x0800, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, modified.time, true);
    view.setUint16(14, modified.date, true);
    view.setUint32(16, crc, true);
    view.setUint32(20, size, true);
    view.setUint32(24, size, true);
    view.setUint16(28, nameBytes.length, true);
    view.setUint16(30, 0, true);
    view.setUint16(32, 0, true);
    view.setUint16(34, 0, true);
    view.setUint16(36, 0, true);
    view.setUint32(38, 0, true);
    view.setUint32(42, offset, true);
    return header;
  }

  async function createStoredZip(files, rootName, setStatus, onProgress) {
    if (!window.TextEncoder || !window.Blob || !window.File) {
      throw new Error("Dieser Browser kann Ordner nicht automatisch als ZIP vorbereiten. Bitte den Ordner manuell als ZIP hochladen.");
    }
    if (files.length > 65535) {
      throw new Error("Der Ordner enthaelt zu viele Dateien fuer ein Browser-ZIP. Bitte den Ordner manuell als ZIP hochladen.");
    }

    const encoder = new TextEncoder();
    const fileParts = [];
    const centralParts = [];
    let offset = 0;
    const totalBytes = files.reduce((sum, file) => sum + Math.max(file.size || 0, 1), 0);
    let processedBytes = 0;

    function reportPreparationProgress() {
      if (onProgress) {
        onProgress(totalBytes ? processedBytes / totalBytes : 0);
      }
    }

    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      if (file.size > zipUint32Max) {
        throw new Error(`Die Datei ${file.name} ist zu gross fuer ein Browser-ZIP.`);
      }
      const entryName = entryNameForFile(file, rootName);
      const nameBytes = encoder.encode(entryName);
      if (!nameBytes.length || nameBytes.length > 65535) {
        throw new Error(`Der Dateiname ${file.name} kann nicht als ZIP-Eintrag geschrieben werden.`);
      }
      setStatus(`ZIP wird vorbereitet (${index + 1}/${files.length}): ${entryName}`);
      const crc = await crc32ForFile(file, (chunkBytes) => {
        processedBytes += chunkBytes;
        reportPreparationProgress();
      });
      if (!file.size) {
        processedBytes += 1;
        reportPreparationProgress();
      }
      const size = file.size >>> 0;
      const modified = dosDateTime(new Date(file.lastModified || Date.now()));
      const localOffset = offset;
      const localHeader = localZipHeader({ crc, size, nameBytes, modified });
      const centralHeader = centralZipHeader({ crc, size, nameBytes, modified, offset: localOffset });
      fileParts.push(localHeader, nameBytes, file);
      centralParts.push(centralHeader, nameBytes);
      offset += localHeader.length + nameBytes.length + file.size;
      if (offset > zipUint32Max) {
        throw new Error("Der Ordner ist zu gross fuer ein Browser-ZIP. Bitte den Ordner manuell als ZIP hochladen.");
      }
    }
    if (onProgress) {
      onProgress(1);
    }

    const centralOffset = offset;
    const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
    if (centralOffset + centralSize > zipUint32Max) {
      throw new Error("Der Ordner ist zu gross fuer ein Browser-ZIP. Bitte den Ordner manuell als ZIP hochladen.");
    }

    const end = new Uint8Array(22);
    const view = new DataView(end.buffer);
    view.setUint32(0, 0x06054b50, true);
    view.setUint16(4, 0, true);
    view.setUint16(6, 0, true);
    view.setUint16(8, files.length, true);
    view.setUint16(10, files.length, true);
    view.setUint32(12, centralSize, true);
    view.setUint32(16, centralOffset, true);
    view.setUint16(20, 0, true);

    return new Blob([...fileParts, ...centralParts, end], { type: "application/zip" });
  }

  function uploadZipWithProgress(form, payload, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open((form.method || "post").toUpperCase(), form.action, true);
      xhr.withCredentials = true;
      if (xhr.upload) {
        xhr.upload.addEventListener("progress", (event) => {
          if (event.lengthComputable && onProgress) {
            onProgress(event.loaded / event.total);
          }
        });
      }
      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 400) {
          if (onProgress) {
            onProgress(1);
          }
          resolve(xhr.responseURL || "/prototype/klassifizieren");
        } else {
          reject(new Error(`Upload fehlgeschlagen (${xhr.status}).`));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("Upload fehlgeschlagen (Netzwerkfehler).")));
      xhr.addEventListener("abort", () => reject(new Error("Upload abgebrochen.")));
      xhr.send(payload);
    });
  }

  document.querySelectorAll("form[data-busy-label]").forEach((form) => {
    if (form.dataset.clientZipFolder === "true") {
      return;
    }
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      if (button && !button.disabled) {
        button.disabled = true;
        button.textContent = form.dataset.busyLabel || "Wird verarbeitet …";
        button.classList.add("is-busy");
      }
    });
  });

  document.querySelectorAll("form[data-client-zip-folder='true']").forEach((form) => {
    const fileInput = form.querySelector("input[type='file'][name='project_files']");
    const button = form.querySelector("button[type='submit']");
    const status = form.querySelector("[data-client-zip-status]");
    const progress = form.querySelector("[data-client-zip-progress]");
    const progressTrack = form.querySelector("[data-client-zip-track]");
    const progressBar = form.querySelector("[data-client-zip-bar]");
    const progressPercent = form.querySelector("[data-client-zip-percent]");
    const originalButtonText = button?.textContent || "Ordner als ZIP importieren";
    const originalStatusText = status?.textContent || "";

    function setStatus(message) {
      if (status) {
        status.textContent = message;
      }
    }

    function setProgress(fraction) {
      if (!progress) {
        return;
      }
      const rawFraction = Math.max(0, Math.min(1, fraction || 0));
      const pct = rawFraction > 0 && rawFraction < 1 ? Math.max(1, Math.round(rawFraction * 100)) : Math.round(rawFraction * 100);
      progress.hidden = false;
      if (progressBar) {
        progressBar.style.width = `${pct}%`;
      }
      if (progressPercent) {
        progressPercent.textContent = `${pct} %`;
      }
      if (progressTrack) {
        progressTrack.setAttribute("aria-valuenow", String(pct));
      }
    }

    function resetProgress() {
      if (!progress) {
        return;
      }
      progress.hidden = true;
      if (progressBar) {
        progressBar.style.width = "0%";
      }
      if (progressPercent) {
        progressPercent.textContent = "0 %";
      }
      if (progressTrack) {
        progressTrack.setAttribute("aria-valuenow", "0");
      }
    }

    if (fileInput) {
      fileInput.addEventListener("change", () => {
        const files = Array.from(fileInput.files || []);
        resetProgress();
        if (!files.length) {
          setStatus(originalStatusText);
          return;
        }
        const totalSize = files.reduce((sum, file) => sum + file.size, 0);
        if (files.length === 1 && /\.zip$/i.test(files[0].name)) {
          setStatus(`ZIP ausgewaehlt: ${files[0].name} (${formatBytes(files[0].size)}).`);
          return;
        }
        setStatus(`${files.length} Dateien ausgewaehlt (${formatBytes(totalSize)}). Beim Import wird daraus eine ZIP-Datei.`);
      });
    }

    form.addEventListener("submit", async (event) => {
      const files = Array.from(fileInput?.files || []);
      if (!files.length) {
        return;
      }
      if (files.length === 1 && /\.zip$/i.test(files[0].name)) {
        if (button && !button.disabled) {
          button.disabled = true;
          button.textContent = "ZIP wird hochgeladen ...";
          button.classList.add("is-busy");
        }
        return;
      }

      event.preventDefault();
      if (button?.disabled) {
        return;
      }

      if (button) {
        button.disabled = true;
        button.textContent = "ZIP wird vorbereitet ...";
        button.classList.add("is-busy");
      }

      try {
        setProgress(0);
        const rootName = rootNameForFiles(files);
        const zipBlob = await createStoredZip(files, rootName, setStatus, (fraction) => {
          setProgress(fraction * 0.5);
        });
        const payload = new FormData();
        form.querySelectorAll("input[type='hidden'][name]").forEach((input) => {
          payload.append(input.name, input.value);
        });
        payload.append("project_files", new File([zipBlob], `${rootName}.zip`, { type: "application/zip" }));

        setStatus(`ZIP wird hochgeladen (${formatBytes(zipBlob.size)}).`);
        if (button) {
          button.textContent = "ZIP wird hochgeladen ...";
        }
        setProgress(0.5);
        const finalUrl = await uploadZipWithProgress(form, payload, (fraction) => {
          setProgress(0.5 + fraction * 0.5);
        });
        window.location.assign(finalUrl);
      } catch (error) {
        resetProgress();
        setStatus(error?.message || "Der ZIP-Upload ist fehlgeschlagen.");
        if (button) {
          button.disabled = false;
          button.textContent = originalButtonText;
          button.classList.remove("is-busy");
        }
      }
    });
  });

  document.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const message = button.getAttribute("data-confirm") || "Aktion wirklich ausfuehren?";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-validate-form]").forEach((form) => {
    const submitButtons = Array.from(form.querySelectorAll("[data-submit-when-valid]"));
    const requiredFields = Array.from(form.querySelectorAll("[required]"));
    const requiredHint = form.querySelector("[data-required-hint]");

    function syncSubmitState() {
      const complete = requiredFields.every((field) => String(field.value || "").trim().length > 0);
      submitButtons.forEach((button) => {
        button.disabled = !complete;
        if (complete) {
          button.removeAttribute("title");
        } else if (!button.title) {
          button.title = "Bitte Projektnamen eintragen";
        }
      });
      if (requiredHint) {
        requiredHint.hidden = complete;
      }
    }

    requiredFields.forEach((field) => {
      field.addEventListener("input", syncSubmitState);
      field.addEventListener("change", syncSubmitState);
    });
    syncSubmitState();
  });

  document.querySelectorAll("[data-image-selection-form]").forEach((form) => {
    const checkboxes = Array.from(form.querySelectorAll("[data-image-selection-checkbox]"));
    const selectAllButton = form.querySelector("[data-image-select-all]");
    const selectionCount = form.querySelector("[data-image-selection-count]");

    function syncImageSelectionCount() {
      if (!selectionCount) {
        return;
      }
      const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
      selectionCount.textContent = `${selectedCount} ausgewaehlt`;
    }

    if (selectAllButton) {
      selectAllButton.addEventListener("click", () => {
        checkboxes.forEach((checkbox) => {
          checkbox.checked = true;
        });
        syncImageSelectionCount();
      });
    }

    checkboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", syncImageSelectionCount);
    });
    syncImageSelectionCount();
  });

  document.querySelectorAll("[data-position-assignment-form]").forEach((form) => {
    const options = Array.from(form.querySelectorAll("[data-assignment-option]"));

    function syncAssignmentOptions() {
      const selectedByImage = new Map();
      options.forEach((option) => {
        const input = option.querySelector("input[type='checkbox']");
        if (input?.checked) {
          selectedByImage.set(option.dataset.imageId, option.dataset.groupId);
        }
      });

      options.forEach((option) => {
        const input = option.querySelector("input[type='checkbox']");
        const selectedGroup = selectedByImage.get(option.dataset.imageId);
        const hiddenByOtherGroup = Boolean(selectedGroup && selectedGroup !== option.dataset.groupId && !input?.checked);
        option.hidden = hiddenByOtherGroup;
      });
    }

    form.addEventListener("change", (event) => {
      if (event.target.matches("input[type='checkbox']")) {
        syncAssignmentOptions();
      }
    });
    syncAssignmentOptions();
  });

  document.querySelectorAll("[data-caption-workbench]").forEach((workbench) => {
    const selectors = Array.from(workbench.querySelectorAll("[data-caption-select]"));
    const panels = Array.from(workbench.querySelectorAll("[data-caption-panel]"));
    const textareas = Array.from(workbench.querySelectorAll("[data-caption-textarea]"));
    const doneCounter = document.querySelector("[data-caption-done-count]");
    const missingCounter = document.querySelector("[data-caption-missing-count]");

    function showCaption(key) {
      selectors.forEach((button) => {
        button.classList.toggle("active", button.dataset.captionSelect === key);
      });
      panels.forEach((panel) => {
        const active = panel.dataset.captionPanel === key;
        panel.hidden = !active;
        panel.classList.toggle("active", active);
      });
    }

    function syncCaptionStatus() {
      let done = 0;
      textareas.forEach((textarea) => {
        const key = textarea.dataset.captionKey;
        const complete = textarea.value.trim().length > 0;
        if (complete) {
          done += 1;
        }
        const status = complete ? "Text erfasst" : "Text fehlt";
        const listStatus = workbench.querySelector(`[data-caption-list-status="${key}"]`);
        const panelStatus = workbench.querySelector(`[data-caption-panel-status="${key}"]`);
        const listButton = workbench.querySelector(`[data-caption-select="${key}"]`);
        if (listStatus) {
          listStatus.textContent = status;
        }
        if (panelStatus) {
          panelStatus.textContent = status;
        }
        if (listButton) {
          listButton.classList.toggle("is-complete", complete);
        }
      });
      if (doneCounter) {
        doneCounter.textContent = `${done} erfasst`;
      }
      if (missingCounter) {
        missingCounter.textContent = `${textareas.length - done} offen`;
      }
    }

    workbench.addEventListener("click", (event) => {
      const button = event.target.closest("[data-caption-select]");
      if (button) {
        showCaption(button.dataset.captionSelect);
        return;
      }
      const editButton = event.target.closest("[data-caption-edit]");
      if (editButton) {
        const key = editButton.dataset.captionEdit;
        const confirmation = workbench.querySelector(`[data-caption-confirmation="${key}"]`);
        const editField = workbench.querySelector(`[data-caption-edit-field="${key}"]`);
        const textarea = workbench.querySelector(`[data-caption-textarea="${key}"], [data-caption-textarea][data-caption-key="${key}"]`);
        const hiddenInput = workbench.querySelector(`[data-caption-hidden][data-caption-key="${key}"]`);
        if (confirmation) {
          confirmation.hidden = true;
        }
        if (editField) {
          editField.hidden = false;
        }
        if (hiddenInput) {
          hiddenInput.disabled = true;
        }
        if (textarea) {
          textarea.disabled = false;
          textarea.name = `caption__${key}`;
          textarea.focus();
        }
        syncCaptionStatus();
      }
    });
    textareas.forEach((textarea) => {
      textarea.addEventListener("input", syncCaptionStatus);
    });
    if (selectors[0]) {
      showCaption(selectors[0].dataset.captionSelect);
    }
    syncCaptionStatus();
  });

  const dailyStatBars = Array.from(document.querySelectorAll("[data-stat-day]"));
  if (dailyStatBars.length) {
    const dailyDetails = Array.from(document.querySelectorAll("[data-stat-detail]"));

    function showDailyStats(dayKey) {
      dailyStatBars.forEach((button) => {
        const active = button.dataset.statDay === dayKey;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      dailyDetails.forEach((detail) => {
        const active = detail.dataset.statDetail === dayKey;
        detail.hidden = !active;
        detail.classList.toggle("active", active);
      });
    }

    dailyStatBars.forEach((button) => {
      button.addEventListener("click", () => {
        showDailyStats(button.dataset.statDay || "");
      });
    });
  }

  const classificationForm = document.querySelector("[data-classification-form]");
  if (!classificationForm) {
    return;
  }

  const treeRows = Array.from(classificationForm.querySelectorAll("[data-tree-row]"));
  const searchInput = classificationForm.querySelector("[data-file-search]");
  const submitButton = classificationForm.querySelector("[data-classification-submit]");
  const roleCards = Array.from(classificationForm.querySelectorAll("[data-role-card]"));
  let activeRole = classificationForm.querySelector("[data-role-card].active")?.dataset.roleKey;
  const collapsedPaths = new Set();

  function setActiveRole(roleKey) {
    activeRole = roleKey;
    roleCards.forEach((card) => {
      card.classList.toggle("active", card.dataset.roleKey === roleKey);
    });
  }

  function pathListFromValue(value) {
    return value
      .split("\n")
      .map((path) => path.trim())
      .filter(Boolean);
  }

  function roleInput(roleKey) {
    return classificationForm.querySelector(`[data-role-input="${roleKey}"]`);
  }

  function roleDisplay(roleKey) {
    return classificationForm.querySelector(`[data-role-value="${roleKey}"]`);
  }

  function roleCard(roleKey) {
    return roleCards.find((card) => card.dataset.roleKey === roleKey);
  }

  function pathsForRole(roleKey) {
    const input = roleInput(roleKey);
    return input ? pathListFromValue(input.value) : [];
  }

  function formatRoleDisplay(paths) {
    if (!paths.length) {
      return "Noch nicht ausgewaehlt";
    }
    if (paths.length === 1) {
      return paths[0];
    }
    return `${paths[0]} (+${paths.length - 1} weitere)`;
  }

  function syncRoleDisplay(roleKey) {
    const display = roleDisplay(roleKey);
    if (display) {
      display.textContent = formatRoleDisplay(pathsForRole(roleKey));
    }
  }

  function updateSelectedBadges() {
    const selectedByPath = new Map();
    roleCards.forEach((card) => {
      const roleKey = card.dataset.roleKey;
      const roleTitle = card.dataset.roleTitle || roleKey;
      pathsForRole(roleKey).forEach((path) => {
        const titles = selectedByPath.get(path) || [];
        titles.push(roleTitle);
        selectedByPath.set(path, titles);
      });
    });

    classificationForm.querySelectorAll("[data-selected-for]").forEach((badge) => {
      const path = badge.dataset.selectedFor || "";
      const titles = selectedByPath.get(path) || [];
      badge.textContent = titles.length ? `Ausgewaehlt fuer: ${titles.join(", ")}` : "";
    });

    treeRows.forEach((row) => {
      const path = row.dataset.treePath || "";
      row.classList.toggle("selected-row", selectedByPath.has(path));
    });
  }

  function setRoleSelection(roleKey, path) {
    const input = roleInput(roleKey);
    const card = roleCard(roleKey);
    if (!input || !card || !path) {
      return;
    }

    const isMultiple = card.dataset.roleMultiple === "true";
    if (isMultiple) {
      const selectedPaths = pathsForRole(roleKey);
      const existingIndex = selectedPaths.indexOf(path);
      if (existingIndex >= 0) {
        selectedPaths.splice(existingIndex, 1);
      } else {
        selectedPaths.push(path);
      }
      input.value = selectedPaths.join("\n");
    } else {
      input.value = path;
    }

    syncRoleDisplay(roleKey);
    updateSubmitState();
    updateSelectedBadges();
  }

  function updateSubmitState() {
    const requiredInputs = classificationForm.querySelectorAll("[data-role-input]");
    const complete = Array.from(requiredInputs).every((input) => pathListFromValue(input.value).length > 0);
    if (submitButton) {
      submitButton.disabled = !complete;
    }
  }

  function isHiddenByCollapsedParent(row) {
    const path = row.dataset.treePath || "";
    for (const collapsedPath of collapsedPaths) {
      if (path !== collapsedPath && path.startsWith(`${collapsedPath}/`)) {
        return true;
      }
    }
    return false;
  }

  function applyTreeVisibility() {
    const query = (searchInput?.value || "").trim().toLowerCase();
    const matchingPaths = new Set();
    if (query) {
      treeRows.forEach((row) => {
        const path = row.dataset.treePath || "";
        const searchable = `${path} ${row.dataset.treeName || ""}`.toLowerCase();
        if (searchable.includes(query)) {
          matchingPaths.add(path);
          const parts = path.split("/");
          for (let index = 1; index < parts.length; index += 1) {
            matchingPaths.add(parts.slice(0, index).join("/"));
          }
        }
      });
    }

    treeRows.forEach((row) => {
      const path = row.dataset.treePath || "";
      const filteredOut = Boolean(query) && !matchingPaths.has(path);
      const hiddenByCollapse = !query && isHiddenByCollapsedParent(row);
      row.hidden = filteredOut || hiddenByCollapse;
    });
  }

  classificationForm.addEventListener("click", (event) => {
    const card = event.target.closest("[data-role-card]");
    if (card) {
      setActiveRole(card.dataset.roleKey);
      return;
    }

    const toggle = event.target.closest("[data-tree-toggle]");
    if (toggle) {
      const row = toggle.closest("[data-tree-row]");
      const path = row?.dataset.treePath;
      if (!row || !path) {
        return;
      }
      if (collapsedPaths.has(path)) {
        collapsedPaths.delete(path);
        row.classList.remove("collapsed");
        toggle.textContent = "v";
        toggle.setAttribute("aria-label", "Ordner einklappen");
      } else {
        collapsedPaths.add(path);
        row.classList.add("collapsed");
        toggle.textContent = ">";
        toggle.setAttribute("aria-label", "Ordner aufklappen");
      }
      applyTreeVisibility();
      return;
    }

    const button = event.target.closest("[data-pick-path]");
    if (button) {
      if (!activeRole) {
        return;
      }
      setRoleSelection(activeRole, button.dataset.pickPath || "");
    }
  });

  if (searchInput) {
    searchInput.addEventListener("input", applyTreeVisibility);
  }

  roleCards.forEach((card) => syncRoleDisplay(card.dataset.roleKey));
  updateSubmitState();
  updateSelectedBadges();
  applyTreeVisibility();
})();
