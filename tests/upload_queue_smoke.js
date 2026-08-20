const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
    const classes = new Set();
    const handlers = {};
    return {
        hidden: false,
        innerHTML: '',
        textContent: '',
        dataset: {},
        attributes: {},
        style: { setProperty() {} },
        classList: {
            toggle(name, force) {
                const enabled = force === undefined ? !classes.has(name) : Boolean(force);
                if (enabled) classes.add(name);
                else classes.delete(name);
                return enabled;
            },
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            contains(name) { return classes.has(name); },
        },
        addEventListener(type, handler) { handlers[type] = handler; },
        dispatch(type, event = {}) { handlers[type]?.(event); },
        setAttribute(name, value) { this.attributes[name] = String(value); },
    };
}

const ids = Object.fromEntries([
    'upload-queue-dock', 'upload-queue-toggle', 'upload-queue-panel',
    'upload-queue-list', 'upload-queue-badge', 'upload-queue-summary',
    'upload-queue-close', 'upload-queue-clear',
].map(id => [id, element()]));

const context = vm.createContext({
    console,
    document: {
        getElementById(id) { return ids[id] || null; },
        createElement() { return element(); },
    },
    window: {
        addEventListener() {},
        PicManagerSecurity: { escapeHTML(value) { return String(value ?? ''); } },
    },
});

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'upload-queue.js'), 'utf8');
vm.runInContext(source, context, { filename: 'upload-queue.js' });

const queue = context.window.uploadQueue;
queue.setOpen(true);
let closePropagationStopped = false;
ids['upload-queue-close'].dispatch('click', {
    stopPropagation() { closePropagationStopped = true; },
});
assert.equal(closePropagationStopped, true);
assert.equal(queue.open, false);
assert.equal(ids['upload-queue-dock'].classList.contains('is-open'), false);
assert.equal(ids['upload-queue-dock'].classList.contains('is-hover-dismissed'), true);
assert.equal(ids['upload-queue-panel'].attributes['aria-hidden'], 'true');
ids['upload-queue-dock'].dispatch('pointerleave');
assert.equal(ids['upload-queue-dock'].classList.contains('is-hover-dismissed'), false);

const id = queue.add({ name: 'one.png', size: 1024 });
assert.equal(queue.get(id).status, 'queued');
queue.update(id, { status: 'uploading', progress: 48 });
assert.equal(queue.get(id).progress, 48);
queue.update(id, { status: 'success', progress: 100 });
queue.clearFinished();
assert.equal(queue.tasks.length, 0);

let retried = 0;
const failedId = queue.add({ name: 'retry.jpg', status: 'failed', retry: async () => { retried += 1; } });
queue.retry(failedId).then(() => {
    assert.equal(retried, 1);
    assert.equal(queue.get(failedId).status, 'queued');
}).catch(error => {
    console.error(error);
    process.exitCode = 1;
});
