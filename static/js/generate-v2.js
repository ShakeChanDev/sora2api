(() => {
  const $ = (id) => document.getElementById(id);

  const DEFAULT_MODEL = 'sora2-portrait-10s';
  const MAX_REFERENCES = 5;
  const FORM_STORAGE_KEY = 'gen_v2_form_v1';
  const TASK_STORAGE_KEY = 'gen_v2_tasks_v1';
  const ADMIN_TOKEN_KEY = 'adminToken';

  const apiKeyInput = $('apiKey');
  const baseUrlInput = $('baseUrl');
  const modelSelect = $('model');
  const promptInput = $('prompt');
  const imageInput = $('imageInput');
  const imagePreview = $('imagePreview');
  const imagePreviewEmpty = $('imagePreviewEmpty');
  const clearImageBtn = $('clearImageBtn');
  const referenceCounter = $('referenceCounter');
  const referencesState = $('referencesState');
  const referenceGrid = $('referenceGrid');
  const submitBtn = $('submitBtn');
  const clearBtn = $('clearBtn');
  const taskList = $('taskList');
  const toastHost = $('toastHost');
  const defaultsNote = $('defaultsNote');

  let references = [];
  let selectedReferenceIds = [];
  let tasks = [];
  let selectedImageFile = null;

  const statusLabels = {
    preparing: '准备中',
    submitting: '提交中',
    generating: '生成中',
    success: '成功',
    error: '失败',
    interrupted: '已中断'
  };

  const postHeight = () => {
    const height = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
    window.parent?.postMessage({ type: 'sora-generate-height', height }, '*');
  };

  const escapeHtml = (value) =>
    String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

  const authHeaders = () => {
    const token = localStorage.getItem(ADMIN_TOKEN_KEY);
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  const showToast = (message, kind = 'info') => {
    const node = document.createElement('div');
    const tone = ['success', 'warn', 'error'].includes(kind) ? kind : 'info';
    node.className = `toast toast-${tone}`;
    node.textContent = message;
    toastHost.appendChild(node);
    window.setTimeout(() => {
      node.style.opacity = '0';
      node.style.transform = 'translateY(8px)';
      node.style.transition = 'opacity .2s ease, transform .2s ease';
      window.setTimeout(() => node.remove(), 220);
    }, 2600);
  };

  const stripMarkdown = (text) =>
    String(text || '')
      .replace(/\*\*/g, '')
      .replace(/```html[\s\S]*?```/g, '')
      .replace(/`/g, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();

  const formatDateTime = (value) => {
    try {
      return new Date(value).toLocaleString('zh-CN', { hour12: false });
    } catch (_) {
      return value || '-';
    }
  };

  const getSelectedModelLabel = () =>
    modelSelect?.selectedOptions?.[0]?.textContent?.trim() || modelSelect.value || DEFAULT_MODEL;

  const clampProgress = (value) => {
    const num = Number(value);
    if (Number.isNaN(num)) return 0;
    return Math.max(0, Math.min(100, num));
  };

  const persistFormState = () => {
    const payload = {
      model: modelSelect.value || DEFAULT_MODEL,
      prompt: promptInput.value || '',
      references: selectedReferenceIds
    };
    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(payload));
  };

  const restoreFormState = () => {
    try {
      const raw = JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}');
      modelSelect.value = raw.model || DEFAULT_MODEL;
      promptInput.value = raw.prompt || '';
      selectedReferenceIds = Array.isArray(raw.references)
        ? raw.references.filter((id) => typeof id === 'string').slice(0, MAX_REFERENCES)
        : [];
    } catch (_) {
      modelSelect.value = DEFAULT_MODEL;
      selectedReferenceIds = [];
    }
  };

  const persistTasks = () => {
    const payload = tasks.map((task) => ({
      id: task.id,
      status: task.status,
      model: task.model,
      modelLabel: task.modelLabel,
      promptSnippet: task.promptSnippet,
      referenceCount: task.referenceCount,
      taskId: task.taskId || '',
      progress: task.progress,
      message: task.message || '',
      mediaUrl: task.mediaUrl || '',
      mediaType: task.mediaType || '',
      error: task.error || '',
      createdAt: task.createdAt
    }));
    sessionStorage.setItem(TASK_STORAGE_KEY, JSON.stringify(payload));
  };

  const restoreTasks = () => {
    try {
      const raw = JSON.parse(sessionStorage.getItem(TASK_STORAGE_KEY) || '[]');
      tasks = Array.isArray(raw) ? raw : [];
      tasks = tasks.map((task) => {
        if (['preparing', 'submitting', 'generating'].includes(task.status)) {
          return {
            ...task,
            status: 'interrupted',
            message: task.message || '页面刷新后中断了实时状态同步，可重新提交。'
          };
        }
        return task;
      });
      persistTasks();
    } catch (_) {
      tasks = [];
    }
  };

  const setDefaultsNote = (text, tone = 'muted') => {
    defaultsNote.textContent = text;
    defaultsNote.style.color = tone === 'error' ? '#dc2626' : tone === 'success' ? '#166534' : '';
  };

  const renderImagePreview = () => {
    if (!selectedImageFile) {
      imagePreview.hidden = true;
      imagePreview.removeAttribute('src');
      imagePreviewEmpty.hidden = false;
      postHeight();
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      imagePreview.src = String(reader.result || '');
      imagePreview.hidden = false;
      imagePreviewEmpty.hidden = true;
      postHeight();
    };
    reader.readAsDataURL(selectedImageFile);
  };

  const clearImage = () => {
    selectedImageFile = null;
    imageInput.value = '';
    renderImagePreview();
  };

  const reconcileSelectedReferences = () => {
    const valid = new Set(references.map((item) => item.reference_id));
    selectedReferenceIds = selectedReferenceIds.filter((id) => valid.has(id)).slice(0, MAX_REFERENCES);
  };

  const renderReferenceCounter = () => {
    referenceCounter.textContent = `已选 ${selectedReferenceIds.length} / ${MAX_REFERENCES}`;
  };

  const renderReferences = () => {
    renderReferenceCounter();
    if (!references.length) {
      referenceGrid.hidden = true;
      referencesState.hidden = false;
      referencesState.textContent = '暂无 reference。你仍然可以只用提示词或首帧图生成。';
      postHeight();
      return;
    }

    referencesState.hidden = true;
    referenceGrid.hidden = false;
    referenceGrid.innerHTML = references
      .map((item) => {
        const selected = selectedReferenceIds.includes(item.reference_id);
        const preview = item.preview_url
          ? `<img src="${escapeHtml(item.preview_url)}" alt="${escapeHtml(item.name)}">`
          : '<div class="ref-thumb-empty">暂无预览</div>';
        return `
          <button type="button" class="ref-card${selected ? ' selected' : ''}" data-reference-id="${escapeHtml(item.reference_id)}" aria-pressed="${selected ? 'true' : 'false'}">
            <div class="ref-thumb">${preview}</div>
            <div class="ref-body">
              <div class="ref-main">
                <div>
                  <div class="ref-name">${escapeHtml(item.name)}</div>
                  <div class="ref-id">${escapeHtml(item.reference_id)}</div>
                </div>
                <span class="ref-type">${escapeHtml(item.type || 'other')}</span>
              </div>
            </div>
          </button>
        `;
      })
      .join('');
    postHeight();
  };

  const setReferencesMessage = (message, tone = 'muted') => {
    referencesState.hidden = false;
    referenceGrid.hidden = true;
    referencesState.textContent = message;
    referencesState.style.color = tone === 'error' ? '#dc2626' : '';
    postHeight();
  };

  const renderTasks = () => {
    if (!tasks.length) {
      taskList.innerHTML =
        '<div class="empty-block">还没有提交任务。填好提示词、首帧图或 References 后开始生成。</div>';
      postHeight();
      return;
    }

    taskList.innerHTML = tasks
      .map((task) => {
        const progress = clampProgress(task.progress);
        const statusClass = `status-${task.status}`;
        const promptSnippet = task.promptSnippet || '(仅首帧图 / References)';
        const preview = task.mediaUrl
          ? task.mediaType === 'image'
            ? `<div class="task-preview"><img src="${escapeHtml(task.mediaUrl)}" alt="生成结果"></div>`
            : `<div class="task-preview"><video src="${escapeHtml(task.mediaUrl)}" controls playsinline preload="metadata"></video></div>`
          : '';
        const action = task.mediaUrl
          ? `<div class="task-actions"><a class="link-btn" href="${escapeHtml(task.mediaUrl)}" target="_blank" rel="noopener noreferrer">打开结果</a></div>`
          : '';
        const taskIdText = task.taskId || '待回传';
        const message = task.error || task.message || '';
        return `
          <article class="task-card">
            <div class="task-head">
              <div class="task-title">
                <div class="task-name">${escapeHtml(promptSnippet)}</div>
                <div class="task-meta">
                  <span>${escapeHtml(task.modelLabel || task.model || DEFAULT_MODEL)}</span>
                  <span>${escapeHtml(formatDateTime(task.createdAt))}</span>
                </div>
              </div>
              <span class="status-badge ${statusClass}">${escapeHtml(statusLabels[task.status] || task.status)}</span>
            </div>
            <div class="progress-wrap">
              <div class="progress-text">${escapeHtml(message || '等待服务端返回状态…')}</div>
              <div class="progress-bar"><div class="progress-fill" style="width:${progress}%;"></div></div>
            </div>
            <div class="task-attrs">
              <div class="task-attr">
                <div class="task-attr-label">Task ID</div>
                <div class="task-attr-value">${escapeHtml(taskIdText)}</div>
              </div>
              <div class="task-attr">
                <div class="task-attr-label">References</div>
                <div class="task-attr-value">${escapeHtml(String(task.referenceCount || 0))}</div>
              </div>
            </div>
            ${preview}
            ${action}
          </article>
        `;
      })
      .join('');
    postHeight();
  };

  const updateTask = (taskId, patch) => {
    tasks = tasks.map((task) => (task.id === taskId ? { ...task, ...patch } : task));
    persistTasks();
    renderTasks();
  };

  const addTask = (meta) => {
    const task = {
      id: `v2-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      status: 'preparing',
      model: meta.model,
      modelLabel: meta.modelLabel,
      promptSnippet: meta.promptSnippet,
      referenceCount: meta.referenceCount,
      taskId: '',
      progress: 2,
      message: '正在准备请求体…',
      mediaUrl: '',
      mediaType: 'video',
      error: '',
      createdAt: new Date().toISOString()
    };
    tasks.unshift(task);
    persistTasks();
    renderTasks();
    return task;
  };

  const fileToDataUrl = (file) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('读取图片失败'));
      reader.readAsDataURL(file);
    });

  const extractTaskIdFromText = (text) => {
    const match = String(text || '').match(/task[_\s-]*id["'：:\s]+([A-Za-z0-9_-]+)/i);
    return match ? match[1] : '';
  };

  const extractTaskId = (obj, rawText) => {
    const structured =
      obj?.choices?.[0]?.delta?.output?.[0]?.task_id ||
      obj?.output?.[0]?.task_id ||
      obj?.task_id ||
      '';
    if (structured) {
      return String(structured);
    }
    return extractTaskIdFromText(rawText);
  };

  const extractProgress = (text) => {
    const match = String(text || '').match(/(\d{1,3})%/);
    if (!match) return null;
    return clampProgress(Number(match[1]));
  };

  const extractMedia = (obj, rawText) => {
    const choice = obj?.choices?.[0] || {};
    const delta = choice.delta || {};
    const rawContent = [
      typeof delta.content === 'string' ? delta.content : '',
      typeof obj?.content === 'string' ? obj.content : '',
      typeof rawText === 'string' ? rawText : ''
    ]
      .filter(Boolean)
      .join('\n');

    const candidates = [
      obj?.url,
      obj?.video_url?.url,
      obj?.image_url?.url,
      obj?.output?.[0]?.url,
      obj?.output?.[0]?.video_url,
      obj?.output?.[0]?.image_url,
      obj?.choices?.[0]?.delta?.output?.[0]?.url,
      obj?.choices?.[0]?.delta?.output?.[0]?.video_url,
      obj?.choices?.[0]?.delta?.output?.[0]?.image_url
    ].filter(Boolean);

    let url = candidates[0] || '';
    if (!url) {
      const htmlMatch = rawContent.match(/<video[^>]+src=['"]([^'"]+)['"]/i);
      if (htmlMatch) url = htmlMatch[1];
    }
    if (!url) {
      const directMatch = rawContent.match(/https?:[^\s)"'<>]+\.(mp4|mov|m4v|webm|png|jpg|jpeg|webp)/i);
      if (directMatch) url = directMatch[0];
    }
    if (!url) return null;
    const mediaType = /\.(png|jpg|jpeg|webp)$/i.test(url) ? 'image' : 'video';
    return { url, mediaType };
  };

  const parseSseMessage = (chunk) => {
    const lines = String(chunk || '')
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());
    if (!lines.length) return null;
    const payload = lines.join('\n').trim();
    return payload || null;
  };

  const buildRequestBody = async () => {
    const prompt = promptInput.value.trim();
    const content = [];
    if (prompt) content.push({ type: 'text', text: prompt });
    if (selectedImageFile) {
      const url = await fileToDataUrl(selectedImageFile);
      content.push({ type: 'image_url', image_url: { url } });
    }
    const body = {
      model: modelSelect.value || DEFAULT_MODEL,
      stream: true,
      messages: [
        {
          role: 'user',
          content: content.length ? content : prompt
        }
      ]
    };
    if (!content.length && !prompt) {
      body.messages[0].content = '';
    }
    if (selectedReferenceIds.length) {
      body.references = [...selectedReferenceIds];
    }
    return body;
  };

  const loadDefaults = async () => {
    baseUrlInput.value = window.location.origin;
    setDefaultsNote('正在读取后台默认值…');
    try {
      const response = await fetch('/api/admin/config', {
        headers: authHeaders()
      });
      if (!response.ok) {
        throw new Error(response.status === 401 ? '管理端登录失效，请重新登录后再打开 v2 面板。' : '读取后台配置失败');
      }
      const payload = await response.json();
      apiKeyInput.value = payload.api_key || '';
      setDefaultsNote('默认值已同步：API Key 来自后台配置，服务器地址来自当前站点。', 'success');
    } catch (error) {
      apiKeyInput.value = '';
      setDefaultsNote(error.message || '读取后台默认值失败', 'error');
      showToast(error.message || '读取后台默认值失败', 'warn');
    }
  };

  const loadReferences = async () => {
    setReferencesMessage('正在加载 reference 列表…');
    try {
      const response = await fetch('/api/references', {
        headers: authHeaders()
      });
      if (!response.ok) {
        throw new Error(response.status === 401 ? '管理端登录失效，无法读取 references。' : '加载 references 失败');
      }
      references = await response.json();
      reconcileSelectedReferences();
      persistFormState();
      renderReferences();
    } catch (error) {
      references = [];
      setReferencesMessage(error.message || '加载 references 失败', 'error');
      showToast(error.message || '加载 references 失败', 'error');
    }
  };

  const handleReferenceClick = (event) => {
    const button = event.target.closest('[data-reference-id]');
    if (!button) return;
    const referenceId = button.getAttribute('data-reference-id');
    if (!referenceId) return;

    const selected = selectedReferenceIds.includes(referenceId);
    if (selected) {
      selectedReferenceIds = selectedReferenceIds.filter((id) => id !== referenceId);
    } else {
      if (selectedReferenceIds.length >= MAX_REFERENCES) {
        showToast(`References 最多只能选 ${MAX_REFERENCES} 个`, 'warn');
        return;
      }
      selectedReferenceIds = [...selectedReferenceIds, referenceId];
    }
    persistFormState();
    renderReferences();
  };

  const buildErrorMessage = async (response) => {
    try {
      const payload = await response.json();
      if (payload?.error?.message) return payload.error.message;
      if (payload?.detail) return payload.detail;
      return response.statusText || '请求失败';
    } catch (_) {
      return response.statusText || '请求失败';
    }
  };

  const runTask = async (task, requestBody, apiKey, baseUrl) => {
    updateTask(task.id, {
      status: 'submitting',
      progress: 8,
      message: '正在提交到 /v1/chat/completions …'
    });

    let contentAggregate = '';

    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestBody)
      });

      if (!response.ok) {
        throw new Error(await buildErrorMessage(response));
      }

      if (!response.body) {
        throw new Error('服务端未返回可读流');
      }

      updateTask(task.id, {
        status: 'generating',
        progress: 12,
        message: '任务已提交，等待服务端推送进度…'
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let boundaryIndex = buffer.indexOf('\n\n');
        while (boundaryIndex >= 0) {
          const rawEvent = buffer.slice(0, boundaryIndex);
          buffer = buffer.slice(boundaryIndex + 2);
          boundaryIndex = buffer.indexOf('\n\n');

          const payload = parseSseMessage(rawEvent);
          if (!payload) continue;
          if (payload === '[DONE]') {
            if (!tasks.find((item) => item.id === task.id)?.mediaUrl && !tasks.find((item) => item.id === task.id)?.error) {
              updateTask(task.id, {
                status: 'success',
                progress: 100,
                message: '流式响应结束，未解析到预览链接。'
              });
            }
            continue;
          }

          let obj;
          try {
            obj = JSON.parse(payload);
          } catch (_) {
            continue;
          }

          if (obj?.error) {
            throw new Error(obj.error.message || '服务端返回错误');
          }

          const choice = obj?.choices?.[0] || {};
          const delta = choice.delta || {};
          const reasoning = typeof delta.reasoning_content === 'string' ? delta.reasoning_content : '';
          const content = typeof delta.content === 'string' ? delta.content : '';
          const combined = [reasoning, content, payload].filter(Boolean).join('\n');

          if (content) contentAggregate += content;

          const maybeTaskId = extractTaskId(obj, combined);
          if (maybeTaskId) {
            updateTask(task.id, { taskId: maybeTaskId });
          }

          const maybeProgress = extractProgress(combined);
          if (maybeProgress !== null) {
            updateTask(task.id, {
              status: 'generating',
              progress: Math.max(maybeProgress, clampProgress(tasks.find((item) => item.id === task.id)?.progress || 0)),
              message: stripMarkdown(reasoning || content || '生成中…') || '生成中…'
            });
          } else if (reasoning || content) {
            updateTask(task.id, {
              status: 'generating',
              message: stripMarkdown(reasoning || content) || '生成中…'
            });
          }

          const media = extractMedia(obj, contentAggregate);
          if (media) {
            updateTask(task.id, {
              status: 'success',
              progress: 100,
              mediaUrl: media.url,
              mediaType: media.mediaType,
              message: '生成完成'
            });
          }

          if (choice.finish_reason && !media && /生成失败|error|failed/i.test(combined)) {
            throw new Error(stripMarkdown(reasoning || content || '生成失败'));
          }
        }

        if (done) break;
      }
    } catch (error) {
      updateTask(task.id, {
        status: 'error',
        progress: 100,
        error: error.message || '生成失败',
        message: error.message || '生成失败'
      });
      showToast(error.message || '生成失败', 'error');
    }
  };

  const handleSubmit = async () => {
    const apiKey = apiKeyInput.value.trim();
    const baseUrl = baseUrlInput.value.trim();
    const prompt = promptInput.value.trim();

    if (!apiKey) {
      showToast('请先填写 API Key', 'error');
      apiKeyInput.focus();
      return;
    }
    if (!baseUrl) {
      showToast('请先填写服务器地址', 'error');
      baseUrlInput.focus();
      return;
    }
    if (!prompt && !selectedImageFile && !selectedReferenceIds.length) {
      showToast('提示词、首帧图、References 至少填一个', 'warn');
      promptInput.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = '正在准备…';

    try {
      const body = await buildRequestBody();
      const task = addTask({
        model: body.model,
        modelLabel: getSelectedModelLabel(),
        promptSnippet: prompt ? prompt.slice(0, 80) : '(仅首帧图 / References)',
        referenceCount: selectedReferenceIds.length
      });
      runTask(task, body, apiKey, baseUrl);
      showToast('任务已提交，正在等待流式返回…', 'success');
    } catch (error) {
      showToast(error.message || '请求体构造失败', 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = '开始生成';
    }
  };

  const handleClear = () => {
    promptInput.value = '';
    modelSelect.value = DEFAULT_MODEL;
    selectedReferenceIds = [];
    clearImage();
    persistFormState();
    renderReferences();
    showToast('已清空输入区域', 'info');
  };

  const bindEvents = () => {
    promptInput.addEventListener('input', persistFormState);
    modelSelect.addEventListener('change', persistFormState);
    clearBtn.addEventListener('click', handleClear);
    submitBtn.addEventListener('click', handleSubmit);
    clearImageBtn.addEventListener('click', clearImage);
    referenceGrid.addEventListener('click', handleReferenceClick);
    imageInput.addEventListener('change', () => {
      const file = imageInput.files?.[0] || null;
      if (!file) {
        clearImage();
        return;
      }
      if (!(file.type || '').startsWith('image/')) {
        clearImage();
        showToast('首帧图只支持图片文件', 'warn');
        return;
      }
      selectedImageFile = file;
      renderImagePreview();
    });
  };

  const initHeightObserver = () => {
    const observer = new ResizeObserver(() => postHeight());
    observer.observe(document.body);
    window.addEventListener('load', postHeight);
    window.addEventListener('resize', postHeight);
  };

  const init = async () => {
    restoreTasks();
    restoreFormState();
    renderImagePreview();
    renderTasks();
    renderReferenceCounter();
    bindEvents();
    initHeightObserver();
    await loadDefaults();
    await loadReferences();
    postHeight();
  };

  init();
})();
