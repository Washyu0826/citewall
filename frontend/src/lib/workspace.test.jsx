import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';

import i18n from './i18n.js';
import { api } from '../api/client.js';
import { CurrentCaseProvider, useCurrentCase } from './currentCase.jsx';
import { queryClient } from './queryClient.js';
import { toast } from './toast.jsx';
import { WorkspaceProvider, useWorkspace, useWorkspaceField } from './workspace.jsx';

// Research 09 FE-L1 / UX-5: the workspace state lives above the routes.

let ws; // the live context value, captured by <Probe>
let currentCase;
let renders = []; // { caseId, hasResult } per render — catches a stale frame

function Probe() {
  ws = useWorkspace();
  currentCase = useCurrentCase();
  renders.push({ caseId: currentCase.caseId, hasResult: ws.fields.result !== undefined });
  return null;
}

function Field() {
  const [value, setValue] = useWorkspaceField('oaText', 'initial');
  return (
    <div>
      <span data-testid="value">{value}</span>
      <button type="button" onClick={() => setValue('typed by the attorney')}>
        type
      </button>
    </div>
  );
}

function Page() {
  const [shown, setShown] = useState(true);
  return (
    <>
      {shown && <Field />}
      <button type="button" onClick={() => setShown((s) => !s)}>
        navigate
      </button>
    </>
  );
}

function renderWorkspace(children = null, path = '/analyze') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CurrentCaseProvider initial="CASE-1">
        <WorkspaceProvider>
          <Probe />
          {children}
        </WorkspaceProvider>
      </CurrentCaseProvider>
    </MemoryRouter>
  );
}

const decided = {
  result: { drafts: [] },
  editors: { R1: { draft: 'd', lines: [{ status: 'accepted', source: 'ai_generated' }] } },
};

/** api.analyze that waits until released, and rejects like fetch on abort. */
function heldAnalyze() {
  const held = {};
  vi.spyOn(api, 'analyze').mockImplementation(
    (_token, _payload, { signal } = {}) =>
      new Promise((resolve, reject) => {
        held.finish = resolve;
        signal?.addEventListener('abort', () => reject(Object.assign(new Error('x'), { cancelled: true })));
      })
  );
  return held;
}

afterEach(() => vi.restoreAllMocks());

describe('WorkspaceProvider', () => {
  it('keeps a field when the page that set it unmounts and comes back', () => {
    renderWorkspace(<Page />);
    fireEvent.click(screen.getByText('type'));
    fireEvent.click(screen.getByText('navigate')); // leave
    expect(screen.queryByTestId('value')).toBeNull();
    fireEvent.click(screen.getByText('navigate')); // come back
    expect(screen.getByTestId('value')).toHaveTextContent('typed by the attorney');
  });

  it('a case switch drops the analysis in the same update, and keeps the typed inputs', async () => {
    renderWorkspace();
    act(() => {
      ws.setField('oaText', 'OA text');
      ws.setField('result', { drafts: [] });
    });
    renders = [];
    await act(() => currentCase.setCaseId('CASE-2'));
    // Never a render with the old result under the new case (W2b-D8): the
    // drop happens in the same update as the switch, not in a later effect.
    expect(renders.some((r) => r.caseId === 'CASE-2' && r.hasResult)).toBe(false);
    expect(currentCase.caseId).toBe('CASE-2');
    expect(ws.fields.result).toBeUndefined();
    expect(ws.fields.oaText).toBe('OA text');
  });

  it('a late answer for a case no longer open is not stored under the new one (W2b-D1)', async () => {
    renderWorkspace();
    await act(() => currentCase.setCaseId('CASE-2'));
    act(() => ws.setCaseBound('CASE-1', 'redactPreview', { redacted: 'old case' }));
    expect(ws.fields.redactPreview).toBeUndefined();
    act(() => ws.setCaseBound('CASE-2', 'redactPreview', { redacted: 'this case' }));
    expect(ws.fields.redactPreview).toEqual({ redacted: 'this case' });
  });

  it('asks before a case switch would throw away sentence decisions (UX-5)', async () => {
    renderWorkspace();
    act(() => {
      ws.setField('result', decided.result);
      ws.setField('editors', decided.editors);
    });

    let switched;
    act(() => {
      switched = currentCase.setCaseId('CASE-2');
    });
    expect(await screen.findByText(i18n.t('workspace.discard.switch_case'))).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('discard-keep'));
    expect(await switched).toBe(false);
    expect(currentCase.caseId).toBe('CASE-1');
    expect(ws.fields.result).toBe(decided.result);

    act(() => {
      switched = currentCase.setCaseId('CASE-2');
    });
    fireEvent.click(await screen.findByTestId('discard-confirm'));
    expect(await switched).toBe(true);
    await waitFor(() => expect(currentCase.caseId).toBe('CASE-2'));
    expect(ws.fields.result).toBeUndefined();
  });

  it('a second question gets a fresh, clickable dialog (CI wave 2b)', async () => {
    renderWorkspace();
    act(() => {
      ws.setField('result', decided.result);
      ws.setField('editors', decided.editors);
    });
    let first;
    act(() => {
      first = ws.confirmDiscard('rerun');
    });
    fireEvent.click(await screen.findByTestId('discard-keep'));
    expect(await first).toBe(false);
    let second;
    act(() => {
      second = ws.confirmDiscard('rerun');
    });
    fireEvent.click(await screen.findByTestId('discard-confirm'));
    expect(await second).toBe(true);
    expect(screen.queryAllByRole('dialog')).toHaveLength(0);
  });

  it('does not ask when nothing would be lost', async () => {
    renderWorkspace();
    act(() => ws.setField('result', { drafts: [] }));
    await expect(ws.confirmDiscard('rerun')).resolves.toBe(true);
    expect(screen.queryByTestId('discard-keep')).toBeNull();
  });

  it('settles an open question when the workspace goes away (logout / 401)', async () => {
    const view = renderWorkspace();
    act(() => {
      ws.setField('result', decided.result);
      ws.setField('editors', decided.editors);
    });
    let pending;
    act(() => {
      pending = ws.confirmDiscard('logout');
    });
    view.unmount();
    await expect(pending).resolves.toBe(false);
  });

  it('warns before the tab closes only while decisions are unsaved', () => {
    const added = vi.spyOn(window, 'addEventListener');
    const removed = vi.spyOn(window, 'removeEventListener');
    renderWorkspace();
    expect(added.mock.calls.some(([type]) => type === 'beforeunload')).toBe(false);
    act(() => {
      ws.setField('result', decided.result);
      ws.setField('editors', decided.editors);
    });
    const handler = added.mock.calls.find(([type]) => type === 'beforeunload')?.[1];
    expect(handler).toBeTypeOf('function');
    const event = { preventDefault: vi.fn(), returnValue: undefined };
    handler(event);
    expect(event.preventDefault).toHaveBeenCalled();
    act(() => ws.setField('editors', {})); // nothing unsaved any more
    expect(removed.mock.calls.some(([type, fn]) => type === 'beforeunload' && fn === handler)).toBe(true);
  });

  it('cancel stops waiting, says so, and refreshes the usage the server still counts', async () => {
    heldAnalyze();
    const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    renderWorkspace();
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    expect(ws.run).not.toBeNull();
    act(() => ws.cancelAnalysis());
    await waitFor(() => expect(ws.run).toBeNull());
    expect(info).toHaveBeenCalledWith(i18n.t('workspace.analysis_cancelled'));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['quota'] });
    expect(ws.fields.error).toBeUndefined();
  });

  it('switching away from a running analysis asks first, then stops waiting for it (W2b-D2, B-12)', async () => {
    heldAnalyze();
    const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
    renderWorkspace();
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });

    let switched;
    act(() => {
      switched = currentCase.setCaseId('CASE-2');
    });
    expect(await screen.findByText(i18n.t('workspace.discard.switch_case_running'))).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('discard-keep'));
    expect(await switched).toBe(false);
    expect(ws.run).not.toBeNull(); // still running for CASE-1

    act(() => {
      switched = currentCase.setCaseId('CASE-2');
    });
    fireEvent.click(await screen.findByTestId('discard-confirm'));
    expect(await switched).toBe(true);
    await waitFor(() => expect(ws.run).toBeNull());
    expect(ws.fields.result).toBeUndefined();
    expect(info).toHaveBeenCalledWith(i18n.t('workspace.result_discarded', { id: 'CASE-1' }));
  });

  it('a superseded run never writes its result over the current one (W2b-D5)', async () => {
    const finishes = [];
    vi.spyOn(api, 'analyze').mockImplementation(() => new Promise((resolve) => finishes.push(resolve)));
    renderWorkspace();
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' }); // replaces the first
    });
    await act(async () => finishes[0]({ drafts: ['old'] }));
    expect(ws.fields.result).toBeUndefined();
    await act(async () => finishes[1]({ drafts: ['new'] }));
    expect(ws.fields.result).toEqual({ drafts: ['new'] });
  });

  it('tells the attorney when an analysis finishes while they are on another page', async () => {
    const held = heldAnalyze();
    const success = vi.spyOn(toast, 'success').mockImplementation(() => {});
    renderWorkspace(null, '/home');
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    await act(async () => held.finish({ drafts: [] }));
    expect(ws.fields.result).toEqual({ drafts: [] });
    expect(success).toHaveBeenCalledWith(i18n.t('workspace.analysis_done', { id: 'CASE-1' }));
  });
});
