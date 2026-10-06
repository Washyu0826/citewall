import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '../api/client.js';
import '../lib/i18n.js';
import { mergeReceipt } from '../lib/workspaceState.js';
import DraftEditor from './DraftEditor.jsx';

afterEach(() => vi.restoreAllMocks());

function renderEditor(draft) {
  render(
    <DraftEditor
      initialDraft={draft}
      citationLookup={{}}
      caseId="CASE-T"
      rejectionId="R1"
      token="tok"
      canExport
      role="attorney"
    />
  );
  return screen.getAllByTestId('draft-line');
}

function editLine(line, text) {
  fireEvent.keyDown(line, { key: 'e' });
  // Scope to the line: the editor also has an "add a line" textbox.
  const box = within(screen.getAllByTestId('draft-line')[0]).getByRole('textbox');
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true });
}

describe('DraftEditor commitEdit — CITATION_REMOVED gate', () => {
  it('splits a zh-TW draft into one line per sentence', () => {
    expect(renderEditor('第一句[CITATION_REMOVED]。第二句。')).toHaveLength(2);
  });

  it('A cannot accept a line that still carries [CITATION_REMOVED]', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    fireEvent.keyDown(first, { key: 'a' });
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });

  it('an edit that keeps the marker leaves the line pending', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    editLine(first, '改寫過但仍有[CITATION_REMOVED]。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });

  it('an edit that removes the marker accepts the line', () => {
    const [first] = renderEditor('第一句[CITATION_REMOVED]。第二句。');
    editLine(first, '已由律師改寫。');
    const line = screen.getAllByTestId('draft-line')[0];
    expect(line).toHaveAttribute('data-status', 'accepted');
    expect(line).toHaveTextContent('已由律師改寫。');
  });
});

describe('DraftEditor — Q14/Q17 [UNSUPPORTED_REF_n] gate', () => {
  const DRAFT = '引證1揭示冷卻板[GROUNDED_REF_1]。惟其未教示無線充電線圈[UNSUPPORTED_REF_1]。';

  it('renders the unsupported ref as a warning pill', () => {
    renderEditor(DRAFT);
    expect(screen.getByTestId('unsupported-ref')).toHaveTextContent('1');
  });

  it('A cannot accept the unsupported sentence, but can accept the supported one', () => {
    const [first, second] = renderEditor(DRAFT);
    fireEvent.keyDown(second, { key: 'a' });
    fireEvent.keyDown(first, { key: 'a' });
    const lines = screen.getAllByTestId('draft-line');
    expect(lines[0]).toHaveAttribute('data-status', 'accepted');
    expect(lines[1]).toHaveAttribute('data-status', 'pending');
    expect(within(lines[1]).getByTestId('line-accept-blocked')).toBeInTheDocument();
  });

  it('an edit that keeps [UNSUPPORTED_REF_n] stays pending; removing it accepts', () => {
    renderEditor('惟其未教示無線充電線圈[UNSUPPORTED_REF_1]。');
    editLine(screen.getAllByTestId('draft-line')[0], '改寫後仍引用[UNSUPPORTED_REF_1]。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
    editLine(screen.getAllByTestId('draft-line')[0], '律師已依前案段落改寫。');
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'accepted');
  });
});

describe('DraftEditor review state survives leaving the page (research 09 FE-L1)', () => {
  const DRAFT = '第一句。第二句。';

  function mount(props) {
    return render(
      <DraftEditor citationLookup={{}} caseId="CASE-T" rejectionId="R1" token="tok" canExport role="attorney" {...props} />
    );
  }

  it('hands every change to onSave and restores it on the next mount', () => {
    let saved;
    const first = mount({ initialDraft: DRAFT, onSave: (s) => (saved = s) });
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'a' });
    expect(saved.lines[0].status).toBe('accepted');
    first.unmount(); // the attorney went to another page

    mount({ initialDraft: DRAFT, saved, onSave: (s) => (saved = s) });
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'accepted');
    expect(screen.getAllByTestId('draft-line')[1]).toHaveAttribute('data-status', 'pending');
  });

  it('ignores a saved review that belongs to a different draft', () => {
    let saved;
    const first = mount({ initialDraft: DRAFT, onSave: (s) => (saved = s) });
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'a' });
    first.unmount();

    mount({ initialDraft: '另一份草稿。', saved });
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });

  // A stand-in for the workspace's editors map (Analyze wires the same calls).
  function workspaceStore() {
    const store = { editors: {}, inFlight: false };
    return {
      store,
      props: () => ({
        saved: store.editors.R1,
        onSave: (s) => (store.editors = { ...store.editors, R1: s }),
        onReceipt: (r) => (store.editors = mergeReceipt(store.editors, 'R1', r)),
        exportInFlight: store.inFlight,
        onExportState: (busy) => (store.inFlight = busy),
      }),
    };
  }

  function startExport() {
    fireEvent.click(screen.getByTestId('signoff-checkbox'));
    fireEvent.click(screen.getByTestId('signoff-export'));
  }

  it('an export that finishes after the page was left is still recorded (review W2b-D3)', async () => {
    let finish;
    vi.spyOn(api, 'exportDraft').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const ws = workspaceStore();
    const view = mount({ initialDraft: '第一句。', ...ws.props() });
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'a' });
    startExport();
    const sent = ws.store.editors.R1.lines;
    view.unmount(); // the attorney left while the sign-off was on its way
    await act(async () => finish({ document: 'doc', signed_off_by: 'alice' }));
    expect(ws.store.editors.R1.exportResult).toEqual({ document: 'doc', signed_off_by: 'alice' });
    expect(ws.store.editors.R1.exportedLines).toBe(sent);
    expect(ws.store.inFlight).toBe(false);
  });

  it('a late receipt does not overwrite sentences changed during the export (review W2b-R1)', async () => {
    let finish;
    vi.spyOn(api, 'exportDraft').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const ws = workspaceStore();
    const view = mount({ initialDraft: DRAFT, ...ws.props() });
    fireEvent.click(screen.getByTestId('signoff-accept-all'));
    startExport();
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[1], { key: 'x' }); // changed mid-export
    view.unmount();
    await act(async () => finish({ document: 'doc' }));
    const entry = ws.store.editors.R1;
    expect(entry.lines[1].status).toBe('excluded'); // the change survived the receipt
    expect(entry.exportedLines).not.toBe(entry.lines); // …and still counts as unsaved
  });

  it('coming back during an export: no second sign-off, and the receipt appears when it lands (review W2b-R2)', async () => {
    let finish;
    const exportSpy = vi.spyOn(api, 'exportDraft').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const ws = workspaceStore();
    const first = mount({ initialDraft: '第一句。', ...ws.props() });
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'a' });
    startExport();
    first.unmount(); // leave…
    const back = mount({ initialDraft: '第一句。', ...ws.props() }); // …and come back
    expect(screen.getByTestId('signoff-export')).toBeDisabled();

    await act(async () => finish({ document: 'doc', signed_off_by: 'alice' }));
    back.rerender(
      <DraftEditor citationLookup={{}} caseId="CASE-T" rejectionId="R1" token="tok" canExport role="attorney" initialDraft="第一句。" {...ws.props()} />
    );
    expect(screen.getByTestId('export-result')).toBeInTheDocument();
    expect(exportSpy).toHaveBeenCalledTimes(1);
    // Adopted with the sentences it covered: nothing counts as unsaved.
    expect(ws.store.editors.R1.exportedLines).toBe(ws.store.editors.R1.lines);
    // The next change here keeps the receipt in the workspace (it used to
    // save this editor's empty receipt over it).
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'x' });
    expect(ws.store.editors.R1.exportResult).toEqual({ document: 'doc', signed_off_by: 'alice' });
    expect(ws.store.editors.R1.lines[0].status).toBe('excluded');
  });

  it('a new draft for the mounted editor still resets the review', () => {
    const view = mount({ initialDraft: DRAFT });
    fireEvent.keyDown(screen.getAllByTestId('draft-line')[0], { key: 'a' });
    view.rerender(
      <DraftEditor initialDraft="新草稿。" citationLookup={{}} caseId="CASE-T" rejectionId="R1" token="tok" canExport role="attorney" />
    );
    expect(screen.getAllByTestId('draft-line')[0]).toHaveAttribute('data-status', 'pending');
  });
});
