import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';

import i18n from './i18n.js';
import { api } from '../api/client.js';
import { CurrentCaseProvider, useCurrentCase } from './currentCase.jsx';
import { toast } from './toast.jsx';
import { WorkspaceProvider, useWorkspace, useWorkspaceField } from './workspace.jsx';

// Research 09 FE-L1 / UX-5: the workspace state lives above the routes.

let ws; // the live context value, captured by <Probe>
let currentCase;

function Probe() {
  ws = useWorkspace();
  currentCase = useCurrentCase();
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

  it('a case switch drops the analysis but keeps the typed inputs', async () => {
    renderWorkspace();
    act(() => {
      ws.setField('oaText', 'OA text');
      ws.setField('result', { drafts: [] });
    });
    await act(() => currentCase.setCaseId('CASE-2'));
    expect(ws.fields.result).toBeUndefined();
    expect(ws.fields.oaText).toBe('OA text');
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

  it('does not ask when nothing would be lost', async () => {
    renderWorkspace();
    act(() => ws.setField('result', { drafts: [] }));
    await expect(ws.confirmDiscard('rerun')).resolves.toBe(true);
    expect(screen.queryByTestId('discard-keep')).toBeNull();
  });

  it('warns before the tab closes only while decisions are unsaved', () => {
    const added = vi.spyOn(window, 'addEventListener');
    renderWorkspace();
    expect(added.mock.calls.some(([type]) => type === 'beforeunload')).toBe(false);
    act(() => {
      ws.setField('result', decided.result);
      ws.setField('editors', decided.editors);
    });
    expect(added.mock.calls.some(([type]) => type === 'beforeunload')).toBe(true);
  });

  it('cancel stops waiting for the analysis and says so', async () => {
    vi.spyOn(api, 'analyze').mockImplementation(
      (_token, _payload, { signal }) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(Object.assign(new Error('x'), { cancelled: true })));
        })
    );
    const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
    renderWorkspace();
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    expect(ws.run).not.toBeNull();
    act(() => ws.cancelAnalysis());
    await waitFor(() => expect(ws.run).toBeNull());
    expect(info).toHaveBeenCalledWith(i18n.t('workspace.analysis_cancelled'));
    expect(ws.fields.error).toBeUndefined();
  });

  it('a result that comes back for a case no longer open is dropped (B-12)', async () => {
    let finish;
    vi.spyOn(api, 'analyze').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
    renderWorkspace();
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    await act(() => currentCase.setCaseId('CASE-2'));
    await act(async () => finish({ drafts: [] }));
    expect(ws.fields.result).toBeUndefined();
    expect(info).toHaveBeenCalledWith(i18n.t('workspace.result_discarded', { id: 'CASE-1' }));
  });

  it('tells the attorney when an analysis finishes while they are on another page', async () => {
    let finish;
    vi.spyOn(api, 'analyze').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const success = vi.spyOn(toast, 'success').mockImplementation(() => {});
    renderWorkspace(null, '/home');
    act(() => {
      ws.startAnalysis('tok', { case_id: 'CASE-1' });
    });
    await act(async () => finish({ drafts: [] }));
    expect(ws.fields.result).toEqual({ drafts: [] });
    expect(success).toHaveBeenCalledWith(i18n.t('workspace.analysis_done', { id: 'CASE-1' }));
  });
});
