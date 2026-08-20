(function () {
    'use strict';

    class ModalModule {
    showModal(title, content, isNested = false) {
        const modalOverlay = document.getElementById('modal-overlay');
        const modalBody = document.getElementById('modal-body');
        const modalDialog = modalOverlay.querySelector('.modal');
        const nextLayer = document.createElement('div');
        nextLayer.className = 'modal-layer modal-body';
        nextLayer.innerHTML = content;

        if (!isNested && modalOverlay.style.display !== 'flex') {
            this.modalPreviousFocus = document.activeElement;
        }
        
        if (isNested) {
            // Keep the original modal layer connected to the document. Both
            // serializing and detaching a file input can clear its FileList.
            const preservedContent = modalBody.lastElementChild;
            if (preservedContent) preservedContent.classList.add('modal-layer-hidden');
            this.modalStack.push({
                title: document.getElementById('modal-title').textContent,
                content: preservedContent,
                focus: document.activeElement
            });
            this.isNestedModal = true;
            modalBody.appendChild(nextLayer);
        } else {
            modalBody.replaceChildren(nextLayer);
        }
        
        document.getElementById('modal-title').textContent = title;
        modalOverlay.style.display = 'flex';
        modalOverlay.setAttribute('aria-hidden', 'false');
        document.querySelector('.app-container')?.setAttribute('inert', '');
        window.requestAnimationFrame(() => {
            const autofocusTarget = nextLayer.querySelector('[autofocus]');
            (autofocusTarget || modalDialog).focus({ preventScroll: true });
        });
    }

    closeModal() {
        const activeLayer = document.getElementById('modal-body')?.lastElementChild;
        if (typeof activeLayer?._onModalClose === 'function') {
            const onModalClose = activeLayer._onModalClose;
            delete activeLayer._onModalClose;
            onModalClose();
        }
        if (document.getElementById('modal-body')?.lastElementChild?.querySelector('.avatar-crop-dialog')) {
            this.releaseAvatarCropState();
        }
        if (this.modalStack.length > 0) {
            // 恢复上一个模态框
            const previous = this.modalStack.pop();
            document.getElementById('modal-title').textContent = previous.title;
            document.getElementById('modal-body').lastElementChild?.remove();
            if (previous.content) previous.content.classList.remove('modal-layer-hidden');
            this.isNestedModal = this.modalStack.length > 0;
            
            // 恢复后重新绑定表单和选择器事件
            this.rebindModalEvents();
            window.requestAnimationFrame(() => {
                if (previous.focus?.isConnected) previous.focus.focus({ preventScroll: true });
            });
        } else {
            const modalOverlay = document.getElementById('modal-overlay');
            modalOverlay.style.display = 'none';
            modalOverlay.setAttribute('aria-hidden', 'true');
            document.querySelector('.app-container')?.removeAttribute('inert');
            this.isNestedModal = false;
            const restoreTarget = this.modalPreviousFocus;
            this.modalPreviousFocus = null;
            if (restoreTarget?.isConnected) restoreTarget.focus({ preventScroll: true });
        }
    }

    trapModalFocus(event) {
        const modal = document.getElementById('modal');
        const activeLayer = document.getElementById('modal-body')?.lastElementChild;
        if (!modal || !activeLayer) return;
        const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        const closeButton = modal.querySelector('.modal-close');
        const focusable = [closeButton, ...activeLayer.querySelectorAll(selector)]
            .filter((element, index, list) => element && !element.hidden && list.indexOf(element) === index);
        if (focusable.length === 0) {
            event.preventDefault();
            modal.focus({ preventScroll: true });
            return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const current = document.activeElement;
        if (event.shiftKey && (current === first || !focusable.includes(current))) {
            event.preventDefault();
            last.focus({ preventScroll: true });
        } else if (!event.shiftKey && (current === last || !focusable.includes(current))) {
            event.preventDefault();
            first.focus({ preventScroll: true });
        }
    }
    
    /**
     * 重新绑定恢复的模态框内的事件
     */
    rebindModalEvents() {
        // 重新绑定temp上传表单
        const tempForm = document.getElementById('temp-upload-form');
        if (tempForm) {
            tempForm.onsubmit = (e) => {
                e.preventDefault();
                const encoded = tempForm.dataset.imageName;
                if (window.upload && encoded) {
                    window.upload.submitTempUpload(encoded);
                }
            };
            // 恢复角色选择器状态
            this.restoreTempCharacterSelector();
        }
        
        // 重新绑定批量上传表单
        const batchItem = document.querySelector('.batch-item');
        if (batchItem) {
            this.restoreBatchSelectors();
        }
        this.restoreImageTagSelectors();
    }

    restoreImageTagSelectors() {
        if (!window.imageTagSelectors) return;
        Object.entries(window.imageTagSelectors).forEach(([id, selector]) => {
            const container = document.getElementById(id);
            if (!container || !selector) return;
            selector.container = container;
            selector.render();
            if (selector.refreshData) selector.refreshData();
        });
    }
    
    /**
     * 恢复temp上传的角色选择器
     */
    async restoreTempCharacterSelector() {
        const groupSelect = document.getElementById('temp-group-select');
        const selectorContainer = document.getElementById('temp-character-selector');
        
        if (!groupSelect || !selectorContainer) return;
        
        // 刷新分组选项
        const groups = await api.getGroups();
        const currentValue = groupSelect.value;
        
        groupSelect.innerHTML = '<option value="">先选分组</option>';
        groups.forEach(group => {
            groupSelect.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`;
        });
        
        // 重新初始化角色选择器
        if (currentValue) {
            const characters = await api.getCharacters(parseInt(currentValue));
            
            // 获取或创建选择器
            let tempCharacterSelector = window.characterSelectors['temp-character-selector'];
            if (!tempCharacterSelector) {
                tempCharacterSelector = new CharacterSelector('temp-character-selector');
                window.characterSelectors['temp-character-selector'] = tempCharacterSelector;
            }
            tempCharacterSelector.setCharacters(characters);
        }
        
        // 重新绑定分组change事件
        groupSelect.addEventListener('change', async () => {
            const groupId = groupSelect.value;
            const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
            if (groupId) {
                const characters = await api.getCharacters(parseInt(groupId));
                if (tempCharacterSelector) {
                    tempCharacterSelector.setCharacters(characters);
                }
            } else {
                if (tempCharacterSelector) {
                    tempCharacterSelector.setCharacters([]);
                }
            }
        });
    }
    
    /**
     * 恢复批量上传的选择器
     */
    async restoreBatchSelectors() {
        const groups = await api.getGroups();
        
        document.querySelectorAll('.batch-group').forEach(select => {
            const currentValue = select.value;
            
            select.innerHTML = '<option value="">先选分组</option>';
            groups.forEach(group => {
                select.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`;
            });
            
            // 如果已选择分组，刷新角色列表
            if (currentValue) {
                const characterSelect = select.parentElement.querySelector('.batch-character');
                api.getCharacters(parseInt(currentValue)).then(characters => {
                    const currentCharacters = Array.from(characterSelect.selectedOptions).map(opt => opt.value);
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        const selected = currentCharacters.includes(String(character.id));
                        characterSelect.innerHTML += `<option value="${character.id}" ${selected ? 'selected' : ''}>${this.escapeHomeRankingText(character.name)}</option>`;
                    });
                    characterSelect.disabled = false;
                });
            }
            
            // 重新绑定change事件
            const newSelect = select.cloneNode(true);
            select.parentNode.replaceChild(newSelect, select);
            
            newSelect.addEventListener('change', async () => {
                const groupId = newSelect.value;
                const characterSelect = newSelect.parentElement.querySelector('.batch-character');
                
                if (groupId) {
                    const characters = await api.getCharacters(parseInt(groupId));
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        characterSelect.innerHTML += `<option value="${character.id}">${this.escapeHomeRankingText(character.name)}</option>`;
                    });
                    characterSelect.disabled = false;
                } else {
                    characterSelect.innerHTML = '<option value="">先选分组</option>';
                    characterSelect.disabled = true;
                }
            });
        });
    }
    
    /**
     * 在嵌套模态框关闭后刷新父模态框内的选择器
     */
    async refreshModalSelectors(newItemId, itemType, groupId = null) {
        // 等待模态框DOM更新
        await new Promise(resolve => setTimeout(resolve, 100));
        if (window.imageTagSelectors) {
            await Promise.all(Object.values(window.imageTagSelectors).map(async selector => {
                if (selector && selector.refreshData) {
                    await selector.refreshData();
                }
            }));
            Object.entries(window.imageTagSelectors).forEach(([id, selector]) => {
                const container = document.getElementById(id);
                if (!container || !container.closest('#modal-body') || !selector) return;
                if (itemType === 'group') {
                    selector.addUnique('group_ids', [newItemId]);
                    selector.notify();
                } else if (itemType === 'character') {
                    selector.addUnique('character_ids', [newItemId]);
                    if (groupId) selector.addUnique('group_ids', [groupId]);
                    selector.notify();
                } else if (itemType === 'feature_tag') {
                    selector.addUnique('feature_tag_ids', [newItemId]);
                    selector.notify();
                }
            });
        }
        
        // 处理temp上传模态框
        const tempGroupSelect = document.getElementById('temp-group-select');
        if (tempGroupSelect) {
            if (itemType === 'group') {
                // 刷新分组选项
                const groups = await api.getGroups();
                tempGroupSelect.innerHTML = '<option value="">先选分组</option>';
                groups.forEach(group => {
                    tempGroupSelect.innerHTML += `<option value="${group.id}" ${group.id == newItemId ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`;
                });
                
                // 自动选中并加载角色
                if (newItemId) {
                    tempGroupSelect.value = newItemId;
                    tempGroupSelect.dispatchEvent(new Event('change'));
                }
            } else if (itemType === 'character' && groupId) {
                // 如果当前分组匹配，刷新角色选择器
                if (tempGroupSelect.value == groupId) {
                    const characters = await api.getCharacters(groupId);
                    const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
                    if (tempCharacterSelector) {
                        tempCharacterSelector.setCharacters(characters);
                        // 自动选中新角色
                        tempCharacterSelector.selectCharacterById(newItemId);
                    }
                } else {
                    // 自动切换到新角色所在的分组
                    tempGroupSelect.value = groupId;
                    const characters = await api.getCharacters(groupId);
                    const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
                    if (tempCharacterSelector) {
                        tempCharacterSelector.setCharacters(characters);
                        tempCharacterSelector.selectCharacterById(newItemId);
                    }
                }
            }
        }
        
        // 处理批量上传模态框中的选择器
        const batchGroups = document.querySelectorAll('.batch-group');
        if (batchGroups.length > 0) {
            const groups = await api.getGroups();
            
            batchGroups.forEach(async select => {
                const currentValue = select.value;
                
                if (itemType === 'group') {
                    // 刷新分组选项
                    select.innerHTML = '<option value="">先选分组</option>';
                    groups.forEach(group => {
                        select.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`;
                    });
                } else if (itemType === 'character' && currentValue == groupId) {
                    // 刷新角色选项
                    const characterSelect = select.parentElement.querySelector('.batch-character');
                    const characters = await api.getCharacters(parseInt(currentValue));
                    const currentChars = Array.from(characterSelect.selectedOptions).map(opt => opt.value);
                    
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        const selected = currentChars.includes(String(character.id)) || character.id == newItemId;
                        characterSelect.innerHTML += `<option value="${character.id}" ${selected ? 'selected' : ''}>${this.escapeHomeRankingText(character.name)}</option>`;
                    });
                }
            });
        }
        
        // 处理单张上传的选择器
        const singleGroupSelect = document.getElementById('single-group-select');
        if (singleGroupSelect && document.getElementById('single-upload-form').style.display !== 'none') {
            if (itemType === 'group') {
                const groups = await api.getGroups();
                const currentValue = singleGroupSelect.value;
                
                singleGroupSelect.innerHTML = '<option value="">先选分组</option>';
                groups.forEach(group => {
                    singleGroupSelect.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`;
                });
                
                // 选中新分组
                singleGroupSelect.value = newItemId;
                singleGroupSelect.dispatchEvent(new Event('change'));
            } else if (itemType === 'character' && groupId) {
                // 确保分组正确
                if (singleGroupSelect.value != groupId) {
                    singleGroupSelect.value = groupId;
                }
                
                const characters = await api.getCharacters(groupId);
                if (upload.singleCharacterSelector) {
                    upload.singleCharacterSelector.setCharacters(characters);
                    upload.singleCharacterSelector.selectCharacterById(newItemId);
                }
            }
        }
    }
    }

    window.PicManagerUIModules = window.PicManagerUIModules || [];
    window.PicManagerUIModules.push(ModalModule);
})();
