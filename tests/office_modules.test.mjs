import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { URL } from 'node:url';

const web = path => new URL(`../web/${path}`, import.meta.url);
const html = readFileSync(web('index.html'), 'utf8');
const scripts = [...html.matchAll(/<script defer src="\/([^"]+)"><\/script>/g)].map(m => m[1]);

function loadPage(extraGlobals = {}) {
  const noop = () => {};
  const context = {
    console, setTimeout: () => 0, clearTimeout: noop, requestAnimationFrame: () => 0, fetch: () => Promise.reject(new Error('offline')),
    Image: class { set src(value) { this._src = value; } }, Option: class {},
    document: { readyState: 'complete', getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], addEventListener: noop, createElement: () => ({ style: {}, getContext: () => null }) },
    localStorage: { getItem: () => null, setItem: noop },
    ...extraGlobals,
  };
  context.window = context;
  context.addEventListener = noop;
  vm.createContext(context);
  return context;
}

describe('office window modules', () => {
  it('index.html loads the shared status table first and the office modules in dependency order', () => {
    const office = scripts.filter(s => s.startsWith('js/office/')).map(s => s.slice('js/office/'.length, -'.js'.length));
    expect(scripts.indexOf('js/status_labels.js')).toBeLessThan(scripts.indexOf('js/dashboard.js'));
    expect(office).toEqual(['sound', 'config', 'scene', 'avatar', 'modal', 'sync']);
    expect(scripts.indexOf('js/office/sync.js')).toBeLessThan(scripts.indexOf('js/office_game.js'));
    expect(scripts.at(-1)).toBe('js/office_game.js');
  });

  it('every script the page lists exists and runs far enough to register what the later modules import', () => {
    const context = loadPage();
    for (const script of scripts.filter(s => s.startsWith('js/office') || s === 'js/status_labels.js')) {
      expect(() => vm.runInContext(readFileSync(web(script), 'utf8'), context, { filename: script }), script).not.toThrow();
    }
    const kit = context.OfficeKit;
    expect(Object.keys(kit).sort()).toEqual(['avatar', 'config', 'modal', 'scene', 'sound', 'sync', 'view']);
    expect(Object.keys(kit.avatar).sort()).toEqual(['addParticle', 'drawHumanAnimeAvatar', 'drawParticles', 'drawPhotoSprite', 'drawSoWorkBubble']);
    expect(typeof kit.scene.drawDepartmentZonedOffice).toBe('function');
    expect(typeof kit.sync.updateGameState).toBe('function');
    expect(typeof kit.modal.select).toBe('function');
    expect(Object.keys(kit.config.characters)).toContain('ai_codex');
    expect(typeof context.OfficeGame.refresh).toBe('function');
    expect(typeof context.OfficeGame.selectCharacter).toBe('function');
  });

  it('modules refer to each other only through names that the other module exports', () => {
    const exported = { sound: ['play', 'toggle', 'isEnabled'], modal: ['isOpen', 'close', 'select', 'setupPortraitMotion', 'selected', 'clearSelectionIf'], view: ['ctx', 'width', 'height', 'tick', 'dpr'] };
    for (const script of scripts.filter(s => s.startsWith('js/office'))) {
      const code = readFileSync(web(script), 'utf8');
      for (const [, space, name] of code.matchAll(/\bK\.(sound|modal|view)\.([A-Za-z_]+)/g)) {
        expect(exported[space], `${script}: K.${space}.${name}`).toContain(name);
      }
    }
  });
});

describe('shared status labels', () => {
  const context = loadPage();
  vm.runInContext(readFileSync(web('js/status_labels.js'), 'utf8'), context);
  const labels = context.StatusLabels;

  it('names every task status in Thai and never shows undefined', () => {
    for (const status of ['queued', 'retry_wait', 'assigned', 'running', 'implementation_done', 'gates', 'waiting_for_independent_review', 'review',
      'ready_for_human_approval', 'approved', 'blocked', 'failed', 'cancelled', 'rejected']) {
      expect(labels.label(status), status).toMatch(/[฀-๿]/);
    }
    expect(labels.label('some_future_status')).toBe('some_future_status');
    expect(labels.label(undefined)).toBe('undefined');
    expect(labels.label('toString')).toBe('toString');
  });

  it('the board and the office window read the same table', () => {
    expect(readFileSync(web('js/dashboard.js'), 'utf8')).toContain('window.StatusLabels.step');
    expect(readFileSync(web('js/office/modal.js'), 'utf8')).toContain('window.StatusLabels.label(');
  });
});
