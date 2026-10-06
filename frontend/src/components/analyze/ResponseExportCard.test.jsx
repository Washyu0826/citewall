import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { api } from '../../api/client.js';
import '../../lib/i18n.js';
import { downloadBase64 } from '../../lib/responseExport.js';
import { toast } from '../../lib/toast.jsx';
import ResponseExportCard from './ResponseExportCard.jsx';

// jsdom cannot save files; the download itself is not under test here.
vi.mock('../../lib/responseExport.js', async (importOriginal) => ({
  ...(await importOriginal()),
  downloadBase64: vi.fn(),
}));

afterEach(() => vi.restoreAllMocks());

const READY = {
  session: { role: 'attorney', token: 'tok' },
  caseId: 'CASE-T',
  rejections: [{ rejection_id: 'R1', rejection_type: 'novelty', affected_claims: [1] }],
  progress: { R1: { total: 1, decided: 1, accepted: 1, segments: [{ text: 's' }] } },
  degraded: false,
};
const RECEIPT = { signed_off_by: 'alice', content_sha256: 'abc', docx_base64: '', filename: 'r.docx' };

function mount(props) {
  return render(<ResponseExportCard {...READY} {...props} />);
}

// The whole-response receipt and the in-flight flag live in the workspace
// (research 09 FE-L1): coming back mid-export must not allow an unintended
// second sign-off (review W2b-R2).
describe('ResponseExportCard — leaving the page during an export', () => {
  it('reports the export as in flight while it runs, and done afterwards', async () => {
    vi.spyOn(toast, 'success').mockImplementation(() => {});
    let finish;
    vi.spyOn(api, 'exportResponse').mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const states = [];
    const onExported = vi.fn();
    mount({ onExportState: (busy) => states.push(busy), onExported });
    fireEvent.click(screen.getByTestId('response-export-confirm'));
    fireEvent.click(screen.getByTestId('response-export-submit'));
    expect(states).toEqual([true]);
    await act(async () => finish(RECEIPT));
    expect(states).toEqual([true, false]);
    expect(onExported).toHaveBeenCalledWith(RECEIPT);
  });

  it('records the receipt even when the local download fails (review W2b-S6)', async () => {
    vi.spyOn(toast, 'error').mockImplementation(() => {});
    downloadBase64.mockImplementationOnce(() => {
      throw new Error('bad base64');
    });
    vi.spyOn(api, 'exportResponse').mockResolvedValue(RECEIPT);
    const onExported = vi.fn();
    mount({ onExported });
    fireEvent.click(screen.getByTestId('response-export-confirm'));
    await act(async () => fireEvent.click(screen.getByTestId('response-export-submit')));
    expect(onExported).toHaveBeenCalledWith(RECEIPT);
  });

  it('a card mounted while an export is in flight cannot start another', () => {
    const exportSpy = vi.spyOn(api, 'exportResponse');
    mount({ inFlight: true });
    fireEvent.click(screen.getByTestId('response-export-confirm'));
    const submit = screen.getByTestId('response-export-submit');
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(exportSpy).not.toHaveBeenCalled();
  });

  it('shows a receipt that lands after it mounted', () => {
    const view = mount({ inFlight: true });
    expect(screen.queryByTestId('response-export-result')).toBeNull();
    view.rerender(<ResponseExportCard {...READY} inFlight={false} savedResult={RECEIPT} />);
    expect(screen.getByTestId('response-export-result')).toHaveTextContent('alice');
    fireEvent.click(screen.getByTestId('response-export-confirm'));
    expect(screen.getByTestId('response-export-submit')).not.toBeDisabled(); // a deliberate re-export stays possible
  });
});
